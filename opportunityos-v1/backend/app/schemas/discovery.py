from typing import Literal
from pydantic import BaseModel, Field, HttpUrl


class SellerInput(BaseModel):
    website: HttpUrl
    company_name: str | None = None
    deck_text: str | None = None
    product_hint: str | None = None


class ICPFilters(BaseModel):
    countries: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    target_functions: list[str] = Field(default_factory=list)
    target_titles: list[str] = Field(default_factory=list)
    headcount_min: int = 50
    headcount_max: int = 5000
    account_limit: int = Field(default=30, ge=5, le=100)
    signal_window_days: int = Field(default=90, ge=7, le=365)


class DiscoveryRequest(BaseModel):
    seller: SellerInput
    icp: ICPFilters


class SignalDefinition(BaseModel):
    name: str
    description: str
    weight: int = Field(ge=1, le=10)
    positive_keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)


class SellerBrain(BaseModel):
    company_name: str
    product_summary: str
    categories: list[str] = Field(default_factory=list)
    problems_solved: list[str] = Field(default_factory=list)
    business_outcomes: list[str] = Field(default_factory=list)
    target_industries: list[str] = Field(default_factory=list)
    target_functions: list[str] = Field(default_factory=list)
    target_titles: list[str] = Field(default_factory=list)
    trigger_signals: list[SignalDefinition] = Field(default_factory=list)


class ICPSegment(BaseModel):
    name: str
    priority: Literal["primary", "secondary", "exploratory"]
    industries: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    headcount_min: int = Field(ge=1)
    headcount_max: int = Field(ge=1)
    target_functions: list[str] = Field(default_factory=list)
    target_titles: list[str] = Field(default_factory=list)
    buying_triggers: list[str] = Field(default_factory=list)
    why_fit: str


class ICPPreview(BaseModel):
    company_name: str
    product_summary: str
    confidence: int = Field(ge=0, le=100)
    recommended_countries: list[str] = Field(default_factory=list)
    recommended_industries: list[str] = Field(default_factory=list)
    recommended_functions: list[str] = Field(default_factory=list)
    recommended_titles: list[str] = Field(default_factory=list)
    headcount_min: int = Field(ge=1)
    headcount_max: int = Field(ge=1)
    account_limit: int = Field(default=30, ge=5, le=100)
    signal_window_days: int = Field(default=90, ge=7, le=365)
    segments: list[ICPSegment] = Field(default_factory=list)
    trigger_signals: list[SignalDefinition] = Field(default_factory=list)
    rationale: str


class CandidateCompany(BaseModel):
    company_name: str
    country: str | None = None
    industry: str | None = None
    why_candidate: str
    evidence_urls: list[str] = Field(default_factory=list)


class CandidateExtraction(BaseModel):
    companies: list[CandidateCompany] = Field(default_factory=list)


class CompanyResolution(BaseModel):
    company_name: str
    website: str | None = None
    confidence: int = Field(ge=0, le=100)


class Evidence(BaseModel):
    title: str
    url: str
    source_type: str
    published_date: str | None = None
    snippet: str
    confidence: int = Field(ge=0, le=100)


class AccountSignal(BaseModel):
    signal: str
    why_it_matters: str
    strength: int = Field(ge=0, le=100)
    evidence: list[Evidence] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    icp_fit: int = Field(ge=0, le=15)
    problem_fit: int = Field(ge=0, le=20)
    signal_strength: int = Field(ge=0, le=20)
    independent_signals: int = Field(ge=0, le=10)
    recency: int = Field(ge=0, le=10)
    business_momentum: int = Field(ge=0, le=10)
    technology_fit: int = Field(ge=0, le=5)
    buyer_access: int = Field(ge=0, le=5)
    evidence_confidence: int = Field(ge=0, le=5)


class BuyerRecommendation(BaseModel):
    title: str
    role: Literal["primary_buyer", "executive_sponsor", "champion", "evaluator"]
    why: str
    preferred_channels: list[str] = Field(default_factory=list)


class RankedAccount(BaseModel):
    company_name: str
    website: str
    country: str | None = None
    headcount: int | None = None
    industry: str | None = None
    score: int = Field(ge=0, le=100)
    tier: Literal["immediate_action", "very_hot", "active", "nurture", "low_priority"]
    why_now: str
    product_fit: str
    signals: list[AccountSignal] = Field(default_factory=list)
    score_breakdown: ScoreBreakdown
    top_buyers: list[BuyerRecommendation] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)


class DiscoveryResponse(BaseModel):
    seller_brain: SellerBrain
    accounts: list[RankedAccount]
    candidate_count: int
    researched_count: int
    provider_status: dict[str, str] = Field(default_factory=dict)
