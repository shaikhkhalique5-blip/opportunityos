import httpx

from app.core.config import settings
from app.schemas.discovery import DiscoveryRequest, SellerBrain


def _size_buckets(min_n: int, max_n: int) -> list[str]:
    buckets = [
        (1, 10, "1-10 employees"),
        (11, 50, "11-50 employees"),
        (51, 200, "51-200 employees"),
        (201, 500, "201-500 employees"),
        (501, 1000, "501-1000 employees"),
        (1001, 5000, "1001-5000 employees"),
        (5001, 10000, "5001-10000 employees"),
        (10001, 10**9, "10001+ employees"),
    ]
    return [label for lo, hi, label in buckets if hi >= min_n and lo <= max_n]


def _company_from_person(person: dict) -> dict | None:
    company = person.get("company") or person.get("organization") or {}
    if isinstance(company, str):
        company = {"name": company}
    name = company.get("name") or person.get("company_name")
    website = company.get("website") or company.get("website_url") or company.get("domain") or person.get("company_website")
    if website and not str(website).startswith(("http://", "https://")):
        website = "https://" + str(website).lstrip("/")
    if not name or not website:
        return None
    location_details = company.get("location_details") or {}
    return {
        "company_name": name,
        "website": website,
        "country": location_details.get("country") or company.get("country") or company.get("location") or person.get("company_location"),
        "headcount": company.get("estimated_number_of_employees") or company.get("employee_count") or company.get("size"),
        "industry": company.get("industry") or person.get("company_industry"),
        "why_candidate": "Matched Amplemarket ICP and buyer-role search filters.",
        "discovery_evidence_urls": [u for u in [company.get("linkedin_url"), website] if u],
        "amplemarket_company_id": company.get("id"),
        "amplemarket_contact": {
            "name": person.get("name") or person.get("full_name"),
            "title": person.get("title") or person.get("job_title"),
            "linkedin_url": person.get("linkedin_url"),
        },
        "provider": "amplemarket_people_search",
    }


async def amplemarket_health() -> dict:
    if not settings.amplemarket_api_key:
        return {"connected": False, "reason": "not_configured"}
    headers = {"Authorization": f"Bearer {settings.amplemarket_api_key}"}
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        try:
            r = await client.get("https://api.amplemarket.com/users", headers=headers, params={"page[size]": "1"})
            return {"connected": r.is_success, "status_code": r.status_code, "reason": "ok" if r.is_success else (r.text or "")[:300]}
        except Exception as exc:
            return {"connected": False, "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}


async def amplemarket_people_search_test() -> dict:
    """One-result provider test. No OpenAI calls and no contact enrichment."""
    if not settings.amplemarket_api_key:
        return {"ok": False, "reason": "not_configured"}
    headers = {"Authorization": f"Bearer {settings.amplemarket_api_key}", "Content-Type": "application/json"}
    body = {"page": 1, "page_size": 1}
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        try:
            r = await client.post("https://api.amplemarket.com/people/search", headers=headers, json=body)
            if not r.is_success:
                return {"ok": False, "status_code": r.status_code, "reason": (r.text or "")[:500]}
            data = r.json()
            rows = data.get("results") or data.get("people") or data.get("data") or []
            if isinstance(rows, dict):
                rows = rows.get("results") or rows.get("people") or []
            sample = None
            if rows:
                person = rows[0]
                company = person.get("company") or person.get("organization") or {}
                if isinstance(company, str):
                    company = {"name": company}
                sample = {
                    "person_name": person.get("name") or person.get("full_name"),
                    "title": person.get("title") or person.get("job_title"),
                    "company": company.get("name") or person.get("company_name"),
                    "company_website": company.get("website") or company.get("website_url") or company.get("domain") or person.get("company_website"),
                }
            return {"ok": True, "status_code": r.status_code, "result_count": len(rows), "sample": sample}
        except Exception as exc:
            return {"ok": False, "reason": f"{type(exc).__name__}: {str(exc)[:250]}"}


async def amplemarket_candidates(req: DiscoveryRequest, brain: SellerBrain) -> list[dict]:
    if not settings.amplemarket_api_key:
        return []
    headers = {"Authorization": f"Bearer {settings.amplemarket_api_key}", "Content-Type": "application/json"}
    body = {
        "company_locations": req.icp.countries,
        "company_sizes": _size_buckets(req.icp.headcount_min, req.icp.headcount_max),
        "company_industries": req.icp.industries or brain.target_industries[:8],
        "person_titles": (req.icp.target_titles or brain.target_titles)[:12],
        "person_job_functions": (req.icp.target_functions or brain.target_functions)[:8],
        "page": 1,
        "page_size": min(max(req.icp.account_limit * 5, 50), 100),
    }
    body = {k: v for k, v in body.items() if v not in (None, [], "")}
    async with httpx.AsyncClient(timeout=40, follow_redirects=True) as client:
        try:
            r = await client.post("https://api.amplemarket.com/people/search", headers=headers, json=body)
            print(f"DISCOVERY amplemarket_http={r.status_code}", flush=True)
            if not r.is_success:
                print(f"DISCOVERY amplemarket_error_body={(r.text or '')[:700]}", flush=True)
                return []
            data = r.json()
            rows = data.get("results") or data.get("people") or data.get("data") or []
            if isinstance(rows, dict):
                rows = rows.get("results") or rows.get("people") or []
            print(f"DISCOVERY amplemarket_people={len(rows)}", flush=True)
            out, seen = [], set()
            for person in rows:
                row = _company_from_person(person)
                if not row:
                    continue
                host = str(row["website"]).lower().replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")
                if not host or host in seen:
                    continue
                seen.add(host)
                out.append(row)
                if len(out) >= max(req.icp.account_limit * 2, 20):
                    break
            print(f"DISCOVERY amplemarket_companies={len(out)}", flush=True)
            return out
        except Exception as exc:
            print(f"DISCOVERY amplemarket_error={type(exc).__name__}: {str(exc)[:300]}", flush=True)
            return []
