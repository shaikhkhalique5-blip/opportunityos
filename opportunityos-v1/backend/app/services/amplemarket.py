import httpx

from app.core.config import settings
from app.schemas.discovery import DiscoveryRequest, SellerBrain


def _size_buckets(min_n: int, max_n: int) -> list[str]:
    buckets = [
        (1, 10, "1-10 employees"), (11, 50, "11-50 employees"),
        (51, 200, "51-200 employees"), (201, 500, "201-500 employees"),
        (501, 1000, "501-1000 employees"), (1001, 5000, "1001-5000 employees"),
        (5001, 10000, "5001-10000 employees"), (10001, 10**9, "10001+ employees"),
    ]
    return [label for lo, hi, label in buckets if hi >= min_n and lo <= max_n]


async def amplemarket_candidates(req: DiscoveryRequest, brain: SellerBrain) -> list[dict]:
    """Use Amplemarket Searcher as the primary account universe."""
    if not settings.amplemarket_api_key:
        return []

    headers = {
        "Authorization": f"Bearer {settings.amplemarket_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "company_locations": req.icp.countries,
        "company_sizes": _size_buckets(req.icp.headcount_min, req.icp.headcount_max),
        "company_industries": req.icp.industries,
        "company_focuses": ["b2b"],
        "page": 1,
        "page_size": min(max(req.icp.account_limit * 3, 30), 100),
    }
    # Avoid sending empty filters; Amplemarket treats omitted filters more predictably.
    body = {k: v for k, v in body.items() if v not in (None, [], "")}

    async with httpx.AsyncClient(timeout=40, follow_redirects=True) as client:
        try:
            r = await client.post("https://api.amplemarket.com/companies/search", headers=headers, json=body)
            print(f"DISCOVERY amplemarket_http={r.status_code}", flush=True)
            if not r.is_success:
                print(f"DISCOVERY amplemarket_error_body={(r.text or '')[:500]}", flush=True)
                return []
            rows = r.json().get("results", [])
            print(f"DISCOVERY amplemarket_results={len(rows)}", flush=True)
            candidates = []
            for x in rows:
                website = x.get("website")
                name = x.get("name")
                if not name or not website:
                    continue
                location = x.get("location_details") or {}
                candidates.append({
                    "company_name": name,
                    "website": website,
                    "country": location.get("country") or x.get("location"),
                    "headcount": x.get("estimated_number_of_employees"),
                    "industry": x.get("industry"),
                    "why_candidate": x.get("overview") or "Matched Amplemarket ICP filters.",
                    "discovery_evidence_urls": [u for u in [x.get("linkedin_url"), website] if u],
                    "amplemarket_company_id": x.get("id"),
                    "provider": "amplemarket_searcher",
                })
            return candidates
        except Exception as exc:
            print(f"DISCOVERY amplemarket_error={type(exc).__name__}: {str(exc)[:250]}", flush=True)
            return []
