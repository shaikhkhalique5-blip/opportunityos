import asyncio
from time import perf_counter
from typing import Callable

from app.core.config import settings
from app.schemas.discovery import DiscoveryRequest, DiscoveryResponse, RankedAccount
from app.services.amplemarket import amplemarket_candidates
from app.services.discovery import (
    _host, _openai_json, apollo_candidates, build_seller_brain, enrich_with_clay,
    public_candidates, research_candidate, tier,
)

ProgressCallback = Callable[[str], None]
TARGET_RESEARCH_COUNT = 30
QUALIFIED_SCORE = 85


def _emit(progress: ProgressCallback | None, stage: str):
    if progress:
        progress(stage)


async def run_discovery(req: DiscoveryRequest, progress: ProgressCallback | None = None) -> DiscoveryResponse:
    started = perf_counter()

    # Keep discovery behavior consistent regardless of an older frontend/client value.
    req.icp.account_limit = TARGET_RESEARCH_COUNT

    _emit(progress, "Building Product Brain")
    brain = await build_seller_brain(req)

    _emit(progress, "Discovering candidate accounts")
    # Amplemarket is primary. Apollo/public web remain additive fallbacks.
    amplemarket, apollo, public = await asyncio.gather(
        amplemarket_candidates(req, brain),
        apollo_candidates(req, brain),
        public_candidates(req, brain),
    )

    merged, seen = [], set()
    for row in amplemarket + apollo + public:
        host = _host(row.get("website") or "")
        if host and host not in seen:
            seen.add(host)
            merged.append(row)
    merged = merged[:TARGET_RESEARCH_COUNT]
    print(
        f"DISCOVERY merged_candidates={len(merged)} target={TARGET_RESEARCH_COUNT} amplemarket={len(amplemarket)} apollo={len(apollo)} public={len(public)}",
        flush=True,
    )
    _emit(progress, f"Candidates selected · {len(merged)}/{TARGET_RESEARCH_COUNT} accounts")

    if not merged:
        status = {
            "amplemarket": "primary_connected" if settings.amplemarket_api_key else "not_configured",
            "apollo": "connected" if settings.apollo_api_key else "not_configured",
            "public_web": "connected" if settings.tavily_api_key else "not_configured",
            "clay": "connected" if settings.clay_webhook_url else "not_configured",
        }
        return DiscoveryResponse(
            seller_brain=brain,
            accounts=[],
            candidate_count=0,
            researched_count=0,
            provider_status=status,
        )

    _emit(progress, f"Enriching candidates · 0/{len(merged)}")
    enriched_done = 0

    async def enrich_one(candidate: dict) -> dict:
        nonlocal enriched_done
        result = await enrich_with_clay(candidate)
        enriched_done += 1
        _emit(progress, f"Enriching candidates · {enriched_done}/{len(merged)}")
        return result

    enriched = await asyncio.gather(*(enrich_one(x) for x in merged))

    _emit(progress, f"Researching accounts · 0/{len(enriched)}")
    researched_done = 0

    async def research_one(candidate: dict) -> dict | None:
        nonlocal researched_done
        try:
            return await research_candidate(candidate, brain)
        except Exception as exc:
            company = candidate.get("company_name", "")
            website = candidate.get("website", "")
            print(
                f"DISCOVERY research_error company={company[:80]} website={website[:160]} error={type(exc).__name__}: {str(exc)[:240]}",
                flush=True,
            )
            return None
        finally:
            researched_done += 1
            _emit(progress, f"Researching accounts · {researched_done}/{len(enriched)}")

    evidence_results = await asyncio.gather(*(research_one(x) for x in enriched))
    evidence = [item for item in evidence_results if item is not None]

    if not evidence:
        status = {
            "amplemarket": "primary_connected" if settings.amplemarket_api_key else "not_configured",
            "apollo": "connected" if settings.apollo_api_key else "not_configured",
            "public_web": "connected" if settings.tavily_api_key else "not_configured",
            "clay": "connected" if settings.clay_webhook_url else "not_configured",
        }
        elapsed = perf_counter() - started
        print(f"DISCOVERY finished qualified=0 elapsed_seconds={elapsed:.1f} reason=no_researchable_candidates", flush=True)
        _emit(progress, f"Complete · 0 opportunities scored {QUALIFIED_SCORE}+")
        return DiscoveryResponse(
            seller_brain=brain,
            accounts=[],
            candidate_count=len(merged),
            researched_count=0,
            provider_status=status,
        )

    # Bound concurrency keeps OpenAI load controlled while ranking the full research batch.
    ranking_concurrency = max(1, min(4, len(evidence)))
    rank_sem = asyncio.Semaphore(ranking_concurrency)
    ranked_done = 0
    _emit(progress, f"Ranking opportunities · 0/{len(evidence)}")

    async def rank_one(item: dict) -> RankedAccount | None:
        nonlocal ranked_done
        async with rank_sem:
            try:
                account = await asyncio.to_thread(
                    _openai_json,
                    "ranked_account",
                    RankedAccount,
                    {
                        "task": (
                            "Rank this account for the seller using only supplied evidence. "
                            "Amplemarket metadata establishes ICP/account identity and may include a buyer contact, but is not itself proof of purchase intent. "
                            "Infer buyer roles only when unsupported person identities are absent. Verify buying-window claims from research evidence. "
                            "Use the scoring rubric strictly. Scores of 85+ require strong product/ICP fit plus credible, observable and sufficiently recent evidence of a buying window. "
                            "Do not inflate scores simply to qualify an account."
                        ),
                        "seller_brain": brain.model_dump(),
                        "icp": req.icp.model_dump(),
                        **item,
                    },
                )
                account.tier = tier(account.score)
                return account
            except Exception as exc:
                company = item.get("candidate", {}).get("company_name", "")
                print(f"DISCOVERY ranking_error company={company[:80]} error={type(exc).__name__}", flush=True)
                return None
            finally:
                ranked_done += 1
                _emit(progress, f"Ranking opportunities · {ranked_done}/{len(evidence)}")

    ranked = await asyncio.gather(*(rank_one(item) for item in evidence))

    # Hard quality gate: only expose accounts scoring 85 or higher to the customer.
    accounts = [account for account in ranked if account is not None and account.score >= QUALIFIED_SCORE]
    accounts.sort(key=lambda x: x.score, reverse=True)

    status = {
        "amplemarket": "primary_connected" if settings.amplemarket_api_key else "not_configured",
        "apollo": "connected" if settings.apollo_api_key else "not_configured",
        "public_web": "connected" if settings.tavily_api_key else "not_configured",
        "clay": "connected" if settings.clay_webhook_url else "not_configured",
    }
    elapsed = perf_counter() - started
    print(
        f"DISCOVERY finished qualified={len(accounts)} threshold={QUALIFIED_SCORE} researched={len(evidence)} elapsed_seconds={elapsed:.1f}",
        flush=True,
    )
    _emit(progress, f"Complete · {len(accounts)} opportunities scored {QUALIFIED_SCORE}+")
    return DiscoveryResponse(
        seller_brain=brain,
        accounts=accounts,
        candidate_count=len(merged),
        researched_count=len(evidence),
        provider_status=status,
    )
