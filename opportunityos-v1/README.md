# Scalee OpportunityOS V1.2

A working vertical slice of **AI Opportunity Intelligence for companies selling AI**.

## End-to-end workflow

**Product Brain -> ICP -> Research Engine -> Opportunity Analyst -> Evidence -> Score -> Buyer Map -> Sales Hook -> Human Feedback**

## What's included

### 1) Research Engine
- Crawls the supplied company website.
- Prioritizes About, News, Press, Blog, Careers/Jobs, Leadership/Team, and company pages.
- Pulls recent Google News RSS results for the company.
- Optional Tavily integration for broader search/news evidence.
- Normalizes each source into URL, source name/type, published date, retrieval date, and clean text.
- Deduplicates sources before reasoning.

### 2) Product Brain
Persist seller context in PostgreSQL:
- product / offer
- markets
- problems solved
- target buyers
- differentiators
- proof points

The Opportunity Analyst receives this context so it asks whether a company's recent change creates a legitimate reason to need the seller's product.

### 3) Opportunity Analyst
Produces:
- ICP fit
- recent buying signals
- why this matters / why now
- likely business problem
- best + secondary buyer
- opportunity score + confidence
- evidence with source/date/confidence
- sales hook
- recommended next action
- rejection reason when the opportunity is weak

The analyst is intentionally Level 3: it investigates and recommends but does **not** send emails or LinkedIn messages.

### 4) Dashboard
- Opportunity Analyst form
- KPI overview
- Product Brain creation + saved brains
- Evidence and signal view
- Score breakdown
- Analysis history
- Human feedback: accepted, rejected, contacted, meeting, SQL, won, lost

The feedback table is the start of the future learning loop.

## Run locally

1. Copy `.env.example` to `.env`.
2. Set `OPENAI_API_KEY`.
3. Optional: set `TAVILY_API_KEY` for broader web research.
4. Run:

```bash
docker compose up
```

5. Open `http://localhost:3000`.
6. API docs: `http://localhost:8000/docs`.

Postgres is included in Docker Compose and tables are created on API startup.

## Important V1 boundaries

This is a real MVP foundation, not a production-grade data platform yet. Public websites can block crawlers and Google News does not replace premium enrichment. Before production, add provider-specific connectors (e.g. Apollo/Crunchbase/tech-stack/job data), authentication, per-workspace isolation, migrations, retry/queue infrastructure, source snapshots, stronger observability, and automated evaluation datasets.

Do **not** add autonomous outbound until opportunity quality and feedback data prove the analyst is reliable.
