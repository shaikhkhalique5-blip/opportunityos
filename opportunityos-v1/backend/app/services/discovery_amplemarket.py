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
TARGET_QUALIFIED_COUNT = 10
QUALIFIED_SCORE = 85
MAX_ROUNDS = 3


def _emit(progress: ProgressCallback | None, stage: str):
    if progress:
        progress(stage)


def _provider_status() -> dict[str, str]:
    return {
        "amplemarket": "primary_connected" if settings.amplemarket_api_key else "not_configured",
        "apollo": "connected" if settings.apollo_api_key else "not_configured",
        "public_web": "connected" if settings.tavily_api_key else "not_configured",
        "clay": "connected" if settings.clay_webhook_url else "not_configured",
    }


async def run_discovery(req: DiscoveryRequest, progress: ProgressCallback | None = None) -> DiscoveryResponse:
    started = perf_counter()
    req.icp.account_limit = TARGET_RESEARCH_COUNT

    _emit(progress, "Building Product Brain")
    brain = await build_seller_brain(req)

    seen_hosts: set[str] = set()
    qualified: list[RankedAccount] = []
    candidate_count = 0
    researched_count = 0

    async def process_batch(candidates: list[dict], round_no: int) -> None:
        nonlocal candidate_count, researched_count, qualified
        if not candidates:
            return

        candidate_count += len(candidates)
        _emit(progress, f"Round {round_no}/{MAX_ROUNDS} · Enriching 0/{len(candidates)}")
        enriched_done = 0

        async def enrich_one(candidate: dict) -> dict:
            nonlocal enriched_done
            result = await enrich_with_clay(candidate)
            enriched_done += 1
            _emit(progress, f"Round {round_no}/{MAX_ROUNDS} · Enriching {enriched_done}/{len(candidates)}")
            return result

        enriched = await asyncio.gather(*(enrich_one(x) for x in candidates))

        _emit(progress, f"Round {round_no}/{MAX_ROUNDS} · Researching 0/{len(enriched)}")
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
                _emit(progress, f"Round {round_no}/{MAX_ROUNDS} · Researching {researched_done}/{len(enriched)}")

        evidence_results = await asyncio.gather(*(research_one(x) for x in enriched))
        evidence = [item for item in evidence_results if item is not None]
        researched_count += len(evidence)
        if not evidence:
            return

        ranking_concurrency = max(1, min(4, len(evidence)))
        rank_sem = asyncio.Semaphore(ranking_concurrency)
        ranked_done = 0
        _emit(progress, f"Round {round_no}/{MAX_ROUNDS} · Ranking 0/{len(evidence)} · Qualified {len(qualified)}/{TARGET_QUALIFIED_COUNT}")

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
                    _emit(progress, f"Round {round_no}/{MAX_ROUNDS} · Ranking {ranked_done}/{len(evidence)} · Qualified {len(qualified)}/{TARGET_QUALIFIED_COUNT}")

        ranked = await asyncio.gather(*(rank_one(item) for item in evidence))
        new_qualified = [account for account in ranked if account is not None and account.score >= QUALIFIED_SCORE]

        existing = {_host(account.website) for account in qualified}
        for account in sorted(new_qualified, key=lambda x: x.score, reverse=True):
            host = _host(account.website)
            if host and host not in existing:
                existing.add(host)
                qualified.append(account)

        qualified.sort(key=lambda x: x.score, reverse=True)
        qualified = qualified[:TARGET_QUALIFIED_COUNT]

    for round_no in range(1, MAX_ROUNDS + 1):
        if len(qualified) >= TARGET_QUALIFIED_COUNT:
            break

        _emit(progress, f"Round {round_no}/{MAX_ROUNDS} · Discovering candidates · Qualified {len(qualified)}/{TARGET_QUALIFIED_COUNT}")

        if round_no == 1:
            amplemarket, apollo, public = await asyncio.gather(
                amplemarket_candidates(req, brain, page=1),
                apollo_candidates(req, brain),
                public_candidates(req, brain),
            )
            pool = amplemarket + apollo + public
            print(
                f"DISCOVERY round=1 amplemarket={len(amplemarket)} apollo={len(apollo)} public={len(public)}",
                flush=True,
            )
        else:
            amplemarket = await amplemarket_candidates(req, brain, page=round_no)
            pool = amplemarket
            print(f"DISCOVERY round={round_no} amplemarket={len(amplemarket)}", flush=True)

        batch = []
        for row in pool:
            host = _host(row.get("website") or "")
            if host and host not in seen_hosts:
                seen_hosts.add(host)
                batch.append(row)
            if len(batch) >= TARGET_RESEARCH_COUNT:
                break

        print(
            f"DISCOVERY round={round_no} selected={len(batch)} qualified_before={len(qualified)}",
            flush=True,
        )

        if not batch:
            break

        await process_batch(batch, round_no)

        print(
            f"DISCOVERY round={round_no} qualified_after={len(qualified)} researched_total={researched_count}",
            flush=True,
        )

    elapsed = perf_counter() - started
    qualified.sort(key=lambda x: x.score, reverse=True)
    qualified = qualified[:TARGET_QUALIFIED_COUNT]

    print(
        f"DISCOVERY finished qualified={len(qualified)} target={TARGET_QUALIFIED_COUNT} threshold={QUALIFIED_SCORE} candidates={candidate_count} researched={researched_count} elapsed_seconds={elapsed:.1f}",
        flush=True,
    )
    _emit(progress, f"Complete · {len(qualified)} opportunities scored {QUALIFIED_SCORE}+ · {researched_count} researched")

    return DiscoveryResponse(
        seller_brain=brain,
        accounts=qualified,
        candidate_count=candidate_count,
        researched_count=researched_count,
        provider_status=_provider_status(),
    )
