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


def make_strict_schema(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            properties = node.get("properties", {})
            node["additionalProperties"] = False
            node["required"] = list(properties.keys())

        for value in node.values():
            make_strict_schema(value)

    elif isinstance(node, list):
        for item in node:
            make_strict_schema(item)

    return node
