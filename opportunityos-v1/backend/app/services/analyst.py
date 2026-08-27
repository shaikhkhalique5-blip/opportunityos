import json
from openai import OpenAI
from app.core.config import settings
from app.schemas.opportunity import OpportunityRequest, OpportunityResponse

SYSTEM_PROMPT = """You are Scalee OpportunityOS, a Level-3 B2B Opportunity Analyst.
Investigate, reason, verify and recommend. Never send outreach and never invent facts.
Every material factual claim must be traceable to supplied research evidence.
Prioritize CHANGE: funding, expansion, hiring, leadership, technology, partnerships, launches,
public problem statements, job descriptions, or recent initiatives that could create demand.
Combine multiple independent signals when possible. A company attribute alone is not a buying signal.
Reject weak opportunities rather than forcing a fit.
Use published dates to judge recency. If a date is missing, lower confidence.
Evidence indexes in signals refer to the final evidence array. Keep evidence concise and non-duplicative.
Scoring weights: ICP fit 25, buying signal strength 25, signal recency 15,
problem relevance 15, decision maker access 10, growth momentum 10.
Return only valid JSON matching the supplied schema.
"""


def analyze(req: OpportunityRequest, research_docs: list[dict], product_brain: dict | None = None) -> OpportunityResponse:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    client = OpenAI(api_key=settings.openai_api_key)
    seller_context = product_brain or {"product_description": req.seller_product}
    payload = {
        "seller_context": seller_context,
        "icp": req.icp.model_dump(),
        "company_url": str(req.company_url),
        "research_documents": research_docs,
        "instruction": "Find a genuine buying window for this seller product. Prefer a well-supported rejection to weak speculation.",
    }
    schema = OpportunityResponse.model_json_schema()
    completion = client.responses.create(
        model=settings.openai_model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload)},
        ],
        text={"format": {"type": "json_schema", "name": "opportunity", "schema": schema, "strict": True}},
    )
    return OpportunityResponse.model_validate_json(completion.output_text)
