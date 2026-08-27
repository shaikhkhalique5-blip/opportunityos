import asyncio
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse, quote_plus
import httpx
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from app.core.config import settings

UA = {"User-Agent": "Mozilla/5.0 OpportunityOS/0.2"}
RESEARCH_HINTS = ("about", "news", "press", "blog", "careers", "jobs", "leadership", "team", "investor", "company")


def _clean_html(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else "Untitled"
    text = " ".join(soup.stripped_strings)
    return title, re.sub(r"\s+", " ", text)


def _extract_date(soup: BeautifulSoup) -> str | None:
    candidates = [
        ("meta", {"property": "article:published_time"}, "content"),
        ("meta", {"name": "date"}, "content"),
        ("meta", {"name": "publish-date"}, "content"),
        ("time", {}, "datetime"),
    ]
    for tag, attrs, key in candidates:
        node = soup.find(tag, attrs=attrs)
        if node and node.get(key):
            return str(node.get(key))[:32]
    return None


async def fetch_page(client: httpx.AsyncClient, url: str, source_type: str = "website") -> dict | None:
    try:
        r = await client.get(url, headers=UA)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "text/html" not in ctype and "xml" not in ctype:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        title, text = _clean_html(r.text)
        if len(text) < 80:
            return None
        return {
            "source_url": str(r.url),
            "source_name": title[:240],
            "source_type": source_type,
            "published_date": _extract_date(soup),
            "retrieved_at": datetime.utcnow().isoformat() + "Z",
            "text": text[:16000],
        }
    except Exception:
        return None


async def discover_site_pages(client: httpx.AsyncClient, base_url: str) -> list[str]:
    base = urlparse(base_url)
    root = f"{base.scheme}://{base.netloc}"
    urls: list[str] = [base_url]
    home = await client.get(base_url, headers=UA)
    if home.is_success:
        soup = BeautifulSoup(home.text, "html.parser")
        scored: list[tuple[int, str]] = []
        for a in soup.find_all("a", href=True):
            href = urljoin(root, a["href"])
            parsed = urlparse(href)
            if parsed.netloc != base.netloc:
                continue
            hay = (href + " " + a.get_text(" ", strip=True)).lower()
            score = sum(1 for h in RESEARCH_HINTS if h in hay)
            if score:
                scored.append((score, href.split("#")[0]))
        for _, href in sorted(scored, reverse=True):
            if href not in urls:
                urls.append(href)
            if len(urls) >= settings.research_max_pages:
                break
    return urls[: settings.research_max_pages]


async def google_news_rss(client: httpx.AsyncClient, company_name: str) -> list[dict]:
    query = quote_plus(f'"{company_name}" company')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        r = await client.get(url, headers=UA)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        docs = []
        for item in root.findall(".//item")[:8]:
            title = item.findtext("title") or "Google News"
            link = item.findtext("link") or url
            published = item.findtext("pubDate")
            description = item.findtext("description") or ""
            clean_description = BeautifulSoup(description, "html.parser").get_text(" ", strip=True)
            docs.append({
                "source_url": link,
                "source_name": title,
                "source_type": "news",
                "published_date": published,
                "retrieved_at": datetime.utcnow().isoformat() + "Z",
                "text": clean_description,
            })
        return docs
    except Exception:
        return []


async def tavily_search(client: httpx.AsyncClient, query: str) -> list[dict]:
    if not settings.tavily_api_key:
        return []
    try:
        r = await client.post("https://api.tavily.com/search", json={
            "api_key": settings.tavily_api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": 8,
            "include_answer": False,
        })
        r.raise_for_status()
        docs = []
        for x in r.json().get("results", []):
            docs.append({
                "source_url": x.get("url", ""),
                "source_name": x.get("title", "Search result"),
                "source_type": "search",
                "published_date": x.get("published_date"),
                "retrieved_at": datetime.utcnow().isoformat() + "Z",
                "text": (x.get("content") or "")[:12000],
            })
        return docs
    except Exception:
        return []


async def research_company(url: str) -> list[dict]:
    timeout = httpx.Timeout(18.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        pages = await discover_site_pages(client, url)
        site_docs = [x for x in await asyncio.gather(*(fetch_page(client, u, "website") for u in pages)) if x]
        company_name = site_docs[0]["source_name"].split("|")[0].split("-")[0].strip() if site_docs else urlparse(url).netloc
        news, web = await asyncio.gather(
            google_news_rss(client, company_name),
            tavily_search(client, f'"{company_name}" funding expansion hiring leadership partnership technology jobs'),
        )
    seen = set()
    merged = []
    for doc in site_docs + news + web:
        key = doc.get("source_url") or doc.get("source_name")
        if key and key not in seen and doc.get("text"):
            seen.add(key)
            merged.append(doc)
    return merged[:20]

# backwards compatibility
async def fetch_company_page(url: str) -> dict:
    docs = await research_company(url)
    if not docs:
        raise RuntimeError("Could not retrieve company research")
    return docs[0]
