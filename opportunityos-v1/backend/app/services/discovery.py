import asyncio
import json
from urllib.parse import urlparse

import httpx
from openai import OpenAI

from app.core.config import settings
from app.schemas.discovery import DiscoveryRequest, DiscoveryResponse, RankedAccount, SellerBrain
from app.services.research import research_company, tavily_search


SYSTEM = """You are Scalee OpportunityOS Universal Discovery.
Understand what a B2B seller offers, derive a category-agnostic buying-signal taxonomy, discover and rank accounts using only supplied evidence, and identify the three most relevant buyer roles.
Never claim private purchase intent. A high score means strong observable evidence of a likely buying window, not certainty that a company is buying.
Every signal must be grounded in supplied source material. 95+ is rare and requires multiple recent independent high-confidence signals.
Score exactly: ICP 15, problem fit 20, signal strength 20, independent signals 10, recency 10, business momentum 10, technology fit 5, buyer access 5, evidence confidence 5.
Return JSON matching the supplied schema."""


def _strict(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            props = node.get("properties", {})
            node["additionalProperties"] = False
            node["required"] = list(props.keys())
        for value in node.values(): _strict(value)
    elif isinstance(node, list):
        for value in node: _strict(value)
    return node


def _openai_json(name: str, schema_model, payload: dict):
    if not settings.openai_api_key: raise RuntimeError("OPENAI_API_KEY is not configured")
    client = OpenAI(api_key=settings.openai_api_key)
    schema = _strict(schema_model.model_json_schema())
    result = client.responses.create(model=settings.openai_model,input=[{"role":"system","content":SYSTEM},{"role":"user","content":json.dumps(payload)}],text={"format":{"type":"json_schema","name":name,"schema":schema,"strict":True}})
    return schema_model.model_validate_json(result.output_text)


async def build_seller_brain(req: DiscoveryRequest) -> SellerBrain:
    docs = await research_company(str(req.seller.website))
    return await asyncio.to_thread(_openai_json,"seller_brain",SellerBrain,{"task":"Build the seller Product Brain and a dynamic public buying-signal taxonomy. Make signals specific to this product, but category agnostic.","seller":req.seller.model_dump(mode="json"),"icp":req.icp.model_dump(),"website_research":docs[:12]})


async def apollo_candidates(req: DiscoveryRequest, brain: SellerBrain) -> list[dict]:
    if not settings.apollo_api_key: return []
    headers={"X-Api-Key":settings.apollo_api_key,"Content-Type":"application/json"}
    body={"organization_locations":req.icp.countries,"organization_num_employees_ranges":[f"{req.icp.headcount_min},{req.icp.headcount_max}"],"q_organization_keyword_tags":req.icp.industries or brain.target_industries,"per_page":min(settings.discovery_max_candidates,100),"page":1}
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r=await client.post("https://api.apollo.io/api/v1/mixed_companies/search",headers=headers,json=body);r.raise_for_status();rows=r.json().get("organizations",[])
            return [{"company_name":x.get("name"),"website":x.get("website_url") or x.get("primary_domain"),"country":x.get("country"),"headcount":x.get("estimated_num_employees"),"industry":x.get("industry"),"provider":"apollo"} for x in rows if x.get("name") and (x.get("website_url") or x.get("primary_domain"))]
        except Exception: return []


async def public_candidates(req: DiscoveryRequest, brain: SellerBrain) -> list[dict]:
    countries=", ".join(req.icp.countries) or "target markets";industries=", ".join(req.icp.industries or brain.target_industries[:5]);signals=", ".join(x.name for x in brain.trigger_signals[:8])
    query=f"companies {countries} {industries} {signals} automation transformation expansion hiring"
    docs=[]
    if settings.tavily_api_key:
        async with httpx.AsyncClient(timeout=30) as client: docs=await tavily_search(client,query)
    else:
        # Free fallback: Google News RSS gives discovery a useful public candidate stream without Tavily.
        import urllib.parse
        rss=f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        async with httpx.AsyncClient(timeout=20,follow_redirects=True) as client:
            try:
                r=await client.get(rss);r.raise_for_status()
                from bs4 import BeautifulSoup
                soup=BeautifulSoup(r.text,"xml")
                for item in soup.find_all("item")[:40]:
                    title=item.title.get_text(" ",strip=True) if item.title else ""
                    source=item.source.get_text(" ",strip=True) if item.source else ""
                    link=item.link.get_text(strip=True) if item.link else ""
                    if source: docs.append({"source_name":source,"source_url":link,"title":title})
            except Exception: pass
    candidates=[]
    for d in docs:
        url=d.get("source_url","");host=urlparse(url).netloc.replace("www.","")
        # News RSS links are aggregators, so source_name is a better candidate label; Apollo/Tavily remain preferred for exact domains.
        if host and "news.google.com" not in host: candidates.append({"company_name":d.get("source_name",host)[:120],"website":f"https://{host}","provider":"public_web"})
    return candidates


async def enrich_with_clay(candidate: dict) -> dict:
    if not settings.clay_webhook_url: return candidate
    async with httpx.AsyncClient(timeout=25) as client:
        try:
            headers={"Authorization":f"Bearer {settings.clay_api_key}"} if settings.clay_api_key else {};r=await client.post(settings.clay_webhook_url,headers=headers,json=candidate)
            if r.is_success and r.headers.get("content-type","").startswith("application/json"): candidate.update(r.json());candidate["provider"]=candidate.get("provider","")+"+clay"
        except Exception: pass
    return candidate


async def research_candidate(candidate: dict, brain: SellerBrain) -> dict:
    docs=await research_company(candidate["website"]);return {"candidate":candidate,"research":docs[:20],"signal_taxonomy":[x.model_dump() for x in brain.trigger_signals]}


def tier(score:int)->str:
    if score>=95:return "immediate_action"
    if score>=85:return "very_hot"
    if score>=70:return "active"
    if score>=50:return "nurture"
    return "low_priority"


async def run_discovery(req: DiscoveryRequest) -> DiscoveryResponse:
    brain=await build_seller_brain(req);apollo,public=await asyncio.gather(apollo_candidates(req,brain),public_candidates(req,brain));merged=[];seen=set()
    for row in apollo+public:
        host=urlparse(row.get("website") or "").netloc.replace("www.","")
        if host and host not in seen: seen.add(host);merged.append(row)
    merged=merged[:req.icp.account_limit];enriched=await asyncio.gather(*(enrich_with_clay(x) for x in merged));evidence=await asyncio.gather(*(research_candidate(x,brain) for x in enriched));accounts=[]
    for item in evidence:
        account=await asyncio.to_thread(_openai_json,"ranked_account",RankedAccount,{"task":"Rank this account for the seller. Use only evidence provided. Infer buyer roles, not unsupported person identities. Set providers from candidate metadata.","seller_brain":brain.model_dump(),"icp":req.icp.model_dump(),**item});account.tier=tier(account.score);accounts.append(account)
    accounts.sort(key=lambda x:x.score,reverse=True)
    status={"apollo":"connected" if settings.apollo_api_key else "not_configured","public_web":"tavily_connected" if settings.tavily_api_key else "free_research_mode","clay":"connected" if settings.clay_webhook_url else "not_configured","amplemarket":"connected" if (settings.amplemarket_api_key or settings.amplemarket_webhook_url) else "not_configured"}
    return DiscoveryResponse(seller_brain=brain,accounts=accounts,candidate_count=len(merged),researched_count=len(evidence),provider_status=status)


async def push_to_amplemarket(account:dict)->dict:
    if not settings.amplemarket_webhook_url:return {"status":"not_configured"}
    headers={"Authorization":f"Bearer {settings.amplemarket_api_key}"} if settings.amplemarket_api_key else {}
    async with httpx.AsyncClient(timeout=25) as client:
        r=await client.post(settings.amplemarket_webhook_url,headers=headers,json=account);r.raise_for_status();return {"status":"sent","http_status":r.status_code}
