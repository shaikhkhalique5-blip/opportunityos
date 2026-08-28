import asyncio
import json
import re
from urllib.parse import urlparse

import httpx
from openai import OpenAI

from app.core.config import settings
from app.schemas.discovery import (
    CandidateExtraction,
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
    "linkedin.com", "www.linkedin.com", "reuters.com", "www.reuters.com",
    "bloomberg.com", "www.bloomberg.com", "forbes.com", "www.forbes.com",
    "businesswire.com", "www.businesswire.com", "prnewswire.com", "www.prnewswire.com",
    "news.google.com", "youtube.com", "www.youtube.com", "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com", "x.com", "twitter.com", "wikipedia.org", "www.wikipedia.org",
}


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
        except Exception:
            return []


def _discovery_queries(req: DiscoveryRequest, brain: SellerBrain) -> list[str]:
    countries = req.icp.countries or ["United States", "UAE", "Saudi Arabia"]
    industries = req.icp.industries or brain.target_industries[:5]
    industry_text = " OR ".join(industries[:4]) if industries else "companies"
    product = brain.product_summary[:220]
    signals = brain.trigger_signals[:8]

    queries = []
    # Search by signal clusters rather than one giant query. This surfaces companies mentioned
    # inside news, job posts, transformation announcements, tenders and partner pages.
    for i in range(0, min(len(signals), 8), 2):
        cluster = signals[i:i + 2]
        signal_text = " OR ".join(s.name for s in cluster)
        queries.append(
            f'({" OR ".join(countries[:5])}) ({industry_text}) companies "{signal_text}" automation transformation expansion hiring'
        )
    queries.append(
        f'({" OR ".join(countries[:5])}) ({industry_text}) companies digital transformation automation operations "{product}"'
    )
    queries.append(
        f'({" OR ".join(countries[:5])}) ({industry_text}) companies hiring director head VP automation transformation operations'
    )
    return queries[:6]


def _compact_search_docs(docs: list[dict]) -> list[dict]:
    compact = []
    for d in docs[:60]:
        compact.append({
            "title": d.get("source_name", ""),
            "url": d.get("source_url", ""),
            "published_date": d.get("published_date"),
            "text": (d.get("text") or "")[:3500],
        })
    return compact


def _name_tokens(name: str) -> list[str]:
    stop = {"the", "group", "company", "holding", "holdings", "limited", "ltd", "llc", "inc", "corp", "corporation", "plc"}
    return [t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) >= 3 and t not in stop]


def _plausible_official_result(company_name: str, result: dict) -> str | None:
    url = result.get("source_url") or ""
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    if not host or host in PUBLISHER_HOSTS:
        return None
    tokens = _name_tokens(company_name)
    hay = f"{host} {result.get('source_name', '')}".lower()
    if tokens and not any(t in hay for t in tokens[:4]):
        return None
    return f"{parsed.scheme or 'https'}://{parsed.netloc}"


async def _resolve_company_website(client: httpx.AsyncClient, company_name: str) -> str | None:
    docs = await tavily_search(client, f'"{company_name}" official website company')
    for d in docs:
        official = _plausible_official_result(company_name, d)
        if official:
            return official
    return None


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

        if not docs:
            return []

        extraction = await asyncio.to_thread(
            _openai_json,
            "candidate_extraction",
            CandidateExtraction,
            {
                "task": (
                    "Extract real target companies mentioned in these public search results. "
                    "Do NOT return publishers, news sites, consultants, software vendors, the seller itself, or generic industry names. "
                    "Prefer operating companies that match the requested countries/industries and where the source suggests a recent change, initiative, hiring pattern, expansion, technology program, operational bottleneck, tender, partnership, or transformation relevant to the seller. "
                    "A company can be included even if its official website is not in the source. Return up to 20 strong candidate companies with the evidence URLs that mention them."
                ),
                "seller": req.seller.model_dump(mode="json"),
                "seller_brain": brain.model_dump(),
                "icp": req.icp.model_dump(),
                "search_results": _compact_search_docs(docs),
            },
        )

        seller_host = urlparse(str(req.seller.website)).netloc.lower().replace("www.", "")
        candidates = []
        seen_names = set()
        for item in extraction.companies[: max(req.icp.account_limit * 2, 12)]:
            name_key = re.sub(r"[^a-z0-9]", "", item.company_name.lower())
            if not name_key or name_key in seen_names:
                continue
            seen_names.add(name_key)
            website = await _resolve_company_website(client, item.company_name)
            if not website:
                continue
            host = urlparse(website).netloc.lower().replace("www.", "")
            if not host or host == seller_host or host in PUBLISHER_HOSTS:
                continue
            candidates.append({
                "company_name": item.company_name,
                "website": website,
                "country": item.country,
                "industry": item.industry,
                "why_candidate": item.why_candidate,
                "discovery_evidence_urls": item.evidence_urls,
                "provider": "tavily+openai_extraction",
            })
            if len(candidates) >= req.icp.account_limit:
                break
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
        except Exception:
            pass
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
        host = urlparse(row.get("website") or "").netloc.replace("www.", "")
        if host and host not in seen:
            seen.add(host)
            merged.append(row)
    merged = merged[: req.icp.account_limit]

    enriched = await asyncio.gather(*(enrich_with_clay(x) for x in merged))
    evidence = await asyncio.gather(*(research_candidate(x, brain) for x in enriched))

    accounts = []
    for item in evidence:
        account = await asyncio.to_thread(
            _openai_json,
            "ranked_account",
            RankedAccount,
            {
                "task": (
                    "Rank this account for the seller. Use only evidence provided. "
                    "Infer buyer roles, not unsupported person identities. "
                    "The candidate's discovery_evidence_urls and why_candidate are leads, not proof; verify the actual buying signals from the research documents. "
                    "Set providers from candidate metadata."
                ),
                "seller_brain": brain.model_dump(),
                "icp": req.icp.model_dump(),
                **item,
            },
        )
        account.tier = tier(account.score)
        accounts.append(account)

    accounts.sort(key=lambda x: x.score, reverse=True)
    status = {
        "apollo": "connected" if settings.apollo_api_key else "not_configured",
        "public_web": "tavily_connected_company_extraction_v2" if settings.tavily_api_key else "not_configured",
        "clay": "connected" if settings.clay_webhook_url else "not_configured",
        "amplemarket": "connected" if (settings.amplemarket_api_key or settings.amplemarket_webhook_url) else "not_configured",
    }
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
