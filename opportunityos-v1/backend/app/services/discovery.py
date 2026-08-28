import asyncio
import json
import re
from urllib.parse import urlparse

import httpx
from openai import OpenAI

from app.core.config import settings
from app.schemas.discovery import (
    CandidateExtraction,
    CompanyResolution,
    DiscoveryRequest,
    DiscoveryResponse,
    RankedAccount,
    SellerBrain,
)
from app.services.research import research_company, tavily_search


SYSTEM = """You are Scalee OpportunityOS Universal Discovery.
Understand what a B2B seller offers, derive a category-agnostic buying-signal taxonomy, discover and rank accounts using only supplied evidence, and identify the three most relevant buyer roles.
Never claim private purchase intent. A high score means strong observable evidence of a likely buying window, not certainty that a company is buying.
Every signal must be grounded in supplied source material. 95+ is rare and requires multiple recent independent high-confidence signals.
Score exactly: ICP 15, problem fit 20, signal strength 20, independent signals 10, recency 10, business momentum 10, technology fit 5, buyer access 5, evidence confidence 5.
Return JSON matching the supplied schema."""

PUBLISHER_HOSTS = {
    "linkedin.com", "reuters.com", "bloomberg.com", "forbes.com",
    "businesswire.com", "prnewswire.com", "news.google.com", "youtube.com",
    "facebook.com", "instagram.com", "x.com", "twitter.com", "wikipedia.org",
    "medium.com", "substack.com", "techcrunch.com", "yahoo.com", "msn.com",
}


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().replace("www.", "")


def _root_url(url: str) -> str | None:
    p = urlparse(url or "")
    if not p.netloc:
        return None
    return f"{p.scheme or 'https'}://{p.netloc}"


def _strict(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            props = node.get("properties", {})
            node["additionalProperties"] = False
            node["required"] = list(props.keys())
        for value in node.values():
            _strict(value)
    elif isinstance(node, list):
        for value in node:
            _strict(value)
    return node


def _openai_json(name: str, schema_model, payload: dict):
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    client = OpenAI(api_key=settings.openai_api_key)
    schema = _strict(schema_model.model_json_schema())
    result = client.responses.create(
        model=settings.openai_model,
        input=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(payload)},
        ],
        text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
    )
    return schema_model.model_validate_json(result.output_text)


async def build_seller_brain(req: DiscoveryRequest) -> SellerBrain:
    docs = await research_company(str(req.seller.website))
    return await asyncio.to_thread(
        _openai_json,
        "seller_brain",
        SellerBrain,
        {
            "task": "Build the seller Product Brain and a dynamic public buying-signal taxonomy. Make signals specific to this product, but category agnostic.",
            "seller": req.seller.model_dump(mode="json"),
            "icp": req.icp.model_dump(),
            "website_research": docs[:12],
        },
    )


async def apollo_candidates(req: DiscoveryRequest, brain: SellerBrain) -> list[dict]:
    if not settings.apollo_api_key:
        return []
    headers = {"X-Api-Key": settings.apollo_api_key, "Content-Type": "application/json"}
    body = {
        "organization_locations": req.icp.countries,
        "organization_num_employees_ranges": [f"{req.icp.headcount_min},{req.icp.headcount_max}"],
        "q_organization_keyword_tags": req.icp.industries or brain.target_industries,
        "per_page": min(settings.discovery_max_candidates, 100),
        "page": 1,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post("https://api.apollo.io/api/v1/mixed_companies/search", headers=headers, json=body)
            r.raise_for_status()
            rows = r.json().get("organizations", [])
            return [
                {
                    "company_name": x.get("name"),
                    "website": x.get("website_url") or x.get("primary_domain"),
                    "country": x.get("country"),
                    "headcount": x.get("estimated_num_employees"),
                    "industry": x.get("industry"),
                    "provider": "apollo",
                }
                for x in rows
                if x.get("name") and (x.get("website_url") or x.get("primary_domain"))
            ]
        except Exception as exc:
            print(f"DISCOVERY apollo_error={type(exc).__name__}", flush=True)
            return []


def _discovery_queries(req: DiscoveryRequest, brain: SellerBrain) -> list[str]:
    countries = req.icp.countries or ["United States", "UAE", "Saudi Arabia"]
    industries = req.icp.industries or brain.target_industries[:5]
    country_text = " OR ".join(countries[:5])
    industry_text = " OR ".join(industries[:4]) if industries else "companies"
    product = brain.product_summary[:180]
    signals = brain.trigger_signals[:8]

    queries = []
    for i in range(0, min(len(signals), 8), 2):
        cluster = signals[i:i + 2]
        signal_text = " OR ".join(s.name for s in cluster)
        queries.append(f'({country_text}) ({industry_text}) "{signal_text}" company expansion hiring transformation automation')
    queries.append(f'({country_text}) ({industry_text}) company digital transformation automation operations "{product}"')
    queries.append(f'({country_text}) ({industry_text}) hiring director head VP automation transformation operations')
    return queries[:6]


def _compact_search_docs(docs: list[dict]) -> list[dict]:
    return [
        {
            "title": d.get("source_name", ""),
            "url": d.get("source_url", ""),
            "published_date": d.get("published_date"),
            "text": (d.get("text") or "")[:3500],
        }
        for d in docs[:60]
    ]


def _name_tokens(name: str) -> list[str]:
    stop = {"the", "group", "company", "holding", "holdings", "limited", "ltd", "llc", "inc", "corp", "corporation", "plc", "co"}
    return [t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) >= 3 and t not in stop]


def _is_publisher(host: str) -> bool:
    return any(host == p or host.endswith("." + p) for p in PUBLISHER_HOSTS)


def _plausible_official_result(company_name: str, result: dict) -> str | None:
    url = result.get("source_url") or ""
    host = _host(url)
    if not host or _is_publisher(host):
        return None
    tokens = _name_tokens(company_name)
    title = (result.get("source_name") or "").lower()
    host_text = host.replace("-", " ").replace("_", " ")
    # Accept when a meaningful company token appears in either the domain or result title.
    if tokens and not any(t in host_text or t in title for t in tokens[:5]):
        return None
    return _root_url(url)


async def _resolve_company_website(client: httpx.AsyncClient, company_name: str) -> str | None:
    queries = [
        f'"{company_name}" official website',
        f'"{company_name}" company homepage',
    ]
    batches = await asyncio.gather(*(tavily_search(client, q) for q in queries))
    docs = []
    seen = set()
    for batch in batches:
        for d in batch:
            url = d.get("source_url") or ""
            if url and url not in seen:
                seen.add(url)
                docs.append(d)

    # Fast deterministic pass.
    for d in docs:
        official = _plausible_official_result(company_name, d)
        if official:
            return official

    if not docs:
        return None

    # LLM-assisted resolution from the actual Tavily results. This avoids dropping a valid
    # company merely because its domain is an abbreviation or parent-brand name.
    try:
        resolution = await asyncio.to_thread(
            _openai_json,
            "company_resolution",
            CompanyResolution,
            {
                "task": (
                    "Identify the official corporate website for this company using ONLY the supplied search results. "
                    "Return null website when unsupported. Do not return a news site, social network, directory, marketplace, or publisher."
                ),
                "company_name": company_name,
                "search_results": _compact_search_docs(docs[:16]),
            },
        )
        if resolution.website and resolution.confidence >= 45:
            root = _root_url(resolution.website)
            host = _host(root or "")
            if root and host and not _is_publisher(host):
                return root
    except Exception as exc:
        print(f"DISCOVERY resolution_llm_error company={company_name[:80]} error={type(exc).__name__}", flush=True)

    # Last safe fallback: a non-publisher result whose title clearly names the company.
    tokens = _name_tokens(company_name)
    for d in docs:
        host = _host(d.get("source_url") or "")
        title = (d.get("source_name") or "").lower()
        if host and not _is_publisher(host) and tokens and sum(1 for t in tokens[:5] if t in title) >= 1:
            return _root_url(d.get("source_url") or "")
    return None


def _fallback_domain_candidates(docs: list[dict], seller_host: str, limit: int) -> list[dict]:
    """Use target-company-owned Tavily result domains when entity extraction/resolution is sparse."""
    rows = []
    seen = set()
    for d in docs:
        url = d.get("source_url") or ""
        host = _host(url)
        if not host or host == seller_host or _is_publisher(host) or host in seen:
            continue
        seen.add(host)
        title = (d.get("source_name") or host).strip()
        rows.append({
            "company_name": title[:120] or host,
            "website": _root_url(url),
            "country": None,
            "industry": None,
            "why_candidate": (d.get("text") or "")[:500],
            "discovery_evidence_urls": [url],
            "provider": "tavily_domain_fallback",
        })
        if len(rows) >= limit:
            break
    return rows


async def public_candidates(req: DiscoveryRequest, brain: SellerBrain) -> list[dict]:
    if not settings.tavily_api_key:
        return []

    queries = _discovery_queries(req, brain)
    async with httpx.AsyncClient(timeout=35, follow_redirects=True) as client:
        batches = await asyncio.gather(*(tavily_search(client, q) for q in queries))
        docs = []
        seen_urls = set()
        for batch in batches:
            for d in batch:
                url = d.get("source_url") or ""
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    docs.append(d)

        print(f"DISCOVERY tavily_queries={len(queries)} tavily_docs={len(docs)}", flush=True)
        if not docs:
            return []

        extraction = await asyncio.to_thread(
            _openai_json,
            "candidate_extraction",
            CandidateExtraction,
            {
                "task": (
                    "Extract real target operating companies mentioned in these public search results. "
                    "Do NOT return publishers, news sites, consultants, software vendors, the seller itself, or generic industry names. "
                    "Prefer companies matching the requested countries/industries where sources suggest a recent change, initiative, hiring pattern, expansion, technology program, operational bottleneck, tender, partnership, or transformation relevant to the seller. "
                    "Return up to 25 candidate companies. The official website is NOT required at this stage."
                ),
                "seller": req.seller.model_dump(mode="json"),
                "seller_brain": brain.model_dump(),
                "icp": req.icp.model_dump(),
                "search_results": _compact_search_docs(docs),
            },
        )
        print(f"DISCOVERY extracted_companies={len(extraction.companies)}", flush=True)

        seller_host = _host(str(req.seller.website))
        raw_items = extraction.companies[: max(req.icp.account_limit * 3, 15)]

        sem = asyncio.Semaphore(5)

        async def resolve(item):
            async with sem:
                website = await _resolve_company_website(client, item.company_name)
                return item, website

        resolved = await asyncio.gather(*(resolve(item) for item in raw_items)) if raw_items else []

        candidates = []
        seen_names = set()
        seen_hosts = set()
        for item, website in resolved:
            name_key = re.sub(r"[^a-z0-9]", "", item.company_name.lower())
            if not name_key or name_key in seen_names or not website:
                continue
            host = _host(website)
            if not host or host == seller_host or _is_publisher(host) or host in seen_hosts:
                continue
            seen_names.add(name_key)
            seen_hosts.add(host)
            candidates.append({
                "company_name": item.company_name,
                "website": website,
                "country": item.country,
                "industry": item.industry,
                "why_candidate": item.why_candidate,
                "discovery_evidence_urls": item.evidence_urls,
                "provider": "tavily+openai_extraction_v3",
            })
            if len(candidates) >= req.icp.account_limit:
                break

        print(f"DISCOVERY resolved_candidates={len(candidates)}", flush=True)

        # Do not return zero simply because domain resolution was too conservative. Tavily often
        # returns company-owned news/careers pages directly; use those root domains as a safe fallback.
        if len(candidates) < min(3, req.icp.account_limit):
            fallbacks = _fallback_domain_candidates(docs, seller_host, req.icp.account_limit)
            for row in fallbacks:
                host = _host(row.get("website") or "")
                if host and host not in seen_hosts:
                    seen_hosts.add(host)
                    candidates.append(row)
                if len(candidates) >= req.icp.account_limit:
                    break
            print(f"DISCOVERY candidates_after_fallback={len(candidates)}", flush=True)

        return candidates


async def enrich_with_clay(candidate: dict) -> dict:
    if not settings.clay_webhook_url:
        return candidate
    async with httpx.AsyncClient(timeout=25) as client:
        try:
            headers = {"Authorization": f"Bearer {settings.clay_api_key}"} if settings.clay_api_key else {}
            r = await client.post(settings.clay_webhook_url, headers=headers, json=candidate)
            if r.is_success and r.headers.get("content-type", "").startswith("application/json"):
                candidate.update(r.json())
                candidate["provider"] = candidate.get("provider", "") + "+clay"
        except Exception as exc:
            print(f"DISCOVERY clay_error={type(exc).__name__}", flush=True)
    return candidate


async def research_candidate(candidate: dict, brain: SellerBrain) -> dict:
    docs = await research_company(candidate["website"])
    return {
        "candidate": candidate,
        "research": docs[:20],
        "signal_taxonomy": [x.model_dump() for x in brain.trigger_signals],
    }


def tier(score: int) -> str:
    if score >= 95:
        return "immediate_action"
    if score >= 85:
        return "very_hot"
    if score >= 70:
        return "active"
    if score >= 50:
        return "nurture"
    return "low_priority"


async def run_discovery(req: DiscoveryRequest) -> DiscoveryResponse:
    brain = await build_seller_brain(req)
    apollo, public = await asyncio.gather(apollo_candidates(req, brain), public_candidates(req, brain))

    merged = []
    seen = set()
    for row in apollo + public:
        host = _host(row.get("website") or "")
        if host and host not in seen:
            seen.add(host)
            merged.append(row)
    merged = merged[: req.icp.account_limit]
    print(f"DISCOVERY merged_candidates={len(merged)} apollo={len(apollo)} public={len(public)}", flush=True)

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
                        "Rank this account for the seller. Use only evidence provided. "
                        "Infer buyer roles, not unsupported person identities. "
                        "The candidate's discovery_evidence_urls and why_candidate are leads, not proof; verify buying signals from the research documents. "
                        "Set providers from candidate metadata."
                    ),
                    "seller_brain": brain.model_dump(),
                    "icp": req.icp.model_dump(),
                    **item,
                },
            )
            account.tier = tier(account.score)
            accounts.append(account)
        except Exception as exc:
            print(f"DISCOVERY ranking_error company={item.get('candidate', {}).get('company_name', '')[:80]} error={type(exc).__name__}", flush=True)

    accounts.sort(key=lambda x: x.score, reverse=True)
    status = {
        "apollo": "connected" if settings.apollo_api_key else "not_configured",
        "public_web": "tavily_connected_company_extraction_v3" if settings.tavily_api_key else "not_configured",
        "clay": "connected" if settings.clay_webhook_url else "not_configured",
        "amplemarket": "connected" if (settings.amplemarket_api_key or settings.amplemarket_webhook_url) else "not_configured",
    }
    print(f"DISCOVERY finished accounts={len(accounts)}", flush=True)
    return DiscoveryResponse(
        seller_brain=brain,
        accounts=accounts,
        candidate_count=len(merged),
        researched_count=len(evidence),
        provider_status=status,
    )


async def push_to_amplemarket(account: dict) -> dict:
    if not settings.amplemarket_webhook_url:
        return {"status": "not_configured"}
    headers = {"Authorization": f"Bearer {settings.amplemarket_api_key}"} if settings.amplemarket_api_key else {}
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.post(settings.amplemarket_webhook_url, headers=headers, json=account)
        r.raise_for_status()
        return {"status": "sent", "http_status": r.status_code}
