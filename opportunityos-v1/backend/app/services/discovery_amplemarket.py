import asyncio

from app.core.config import settings
from app.schemas.discovery import DiscoveryRequest, DiscoveryResponse, RankedAccount
from app.services.amplemarket import amplemarket_candidates
from app.services.discovery import (
    _host, _openai_json, apollo_candidates, build_seller_brain, enrich_with_clay,
    public_candidates, research_candidate, tier,
)


async def run_discovery(req: DiscoveryRequest) -> DiscoveryResponse:
    brain = await build_seller_brain(req)

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
    merged = merged[: req.icp.account_limit]
    print(
        f"DISCOVERY merged_candidates={len(merged)} amplemarket={len(amplemarket)} apollo={len(apollo)} public={len(public)}",
        flush=True,
    )

    enriched = await asyncio.gather(*(enrich_with_clay(x) for x in merged))
    evidence = await asyncio.gather(*(research_candidate(x, brain) for x in enriched))

    accounts = []
    for item in evidence:
        try:
            account = await asyncio.to_thread(
                _openai_json,
                "ranked_account",
                RankedAccount,
                {
                    "task": (
                        "Rank this account for the seller using only supplied evidence. "
                        "Amplemarket metadata establishes ICP/account identity and may include a buyer contact, but is not itself proof of purchase intent. "
                        "Infer buyer roles only when unsupported person identities are absent. Verify buying-window claims from research evidence."
                    ),
                    "seller_brain": brain.model_dump(),
                    "icp": req.icp.model_dump(),
                    **item,
                },
            )
            account.tier = tier(account.score)
            accounts.append(account)
        except Exception as exc:
            company = item.get("candidate", {}).get("company_name", "")
            print(f"DISCOVERY ranking_error company={company[:80]} error={type(exc).__name__}", flush=True)

    accounts.sort(key=lambda x: x.score, reverse=True)
    status = {
        "amplemarket": "primary_connected" if settings.amplemarket_api_key else "not_configured",
        "apollo": "connected" if settings.apollo_api_key else "not_configured",
        "public_web": "connected" if settings.tavily_api_key else "not_configured",
        "clay": "connected" if settings.clay_webhook_url else "not_configured",
    }
    print(f"DISCOVERY finished accounts={len(accounts)}", flush=True)
    return DiscoveryResponse(
        seller_brain=brain,
        accounts=accounts,
        candidate_count=len(merged),
        researched_count=len(evidence),
        provider_status=status,
    )
