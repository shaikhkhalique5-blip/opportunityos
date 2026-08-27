from pydantic import BaseModel, Field, HttpUrl
from typing import List, Literal, Optional

class ICPInput(BaseModel):
    geographies: List[str] = []
    company_size: Optional[str] = None
    industries: List[str] = []
    buyers: List[str] = []

class OpportunityRequest(BaseModel):
    company_url: HttpUrl
    seller_product: Optional[str] = Field(default=None, min_length=5)
    product_brain_id: Optional[int] = None
    icp: ICPInput

class EvidenceItem(BaseModel):
    claim: str
    source_url: str
    source_name: str
    published_date: Optional[str] = None
    confidence: int = Field(ge=0, le=100)

class Signal(BaseModel):
    type: str
    description: str
    recency_days: Optional[int] = None
    strength: int = Field(ge=0, le=100)
    evidence_indexes: List[int] = []

class ScoreBreakdown(BaseModel):
    icp_fit: float
    buying_signal_strength: float
    signal_recency: float
    problem_relevance: float
    decision_maker_access: float
    growth_momentum: float

class OpportunityResponse(BaseModel):
    company: str
    icp_fit: float = Field(ge=0, le=10)
    recent_signals: List[Signal]
    why_this_matters: str
    likely_business_problem: str
    why_now: str
    best_buyer: str
    secondary_buyer: Optional[str] = None
    opportunity_score: int = Field(ge=0, le=100)
    confidence: Literal["Low", "Medium", "High"]
    score_breakdown: ScoreBreakdown
    evidence: List[EvidenceItem]
    sales_hook: str
    recommended_next_action: str
    rejection_reason: Optional[str] = None

class FeedbackInput(BaseModel):
    feedback: Literal["accepted", "rejected", "contacted", "meeting", "sql", "won", "lost"]
    note: Optional[str] = None
