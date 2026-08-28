from datetime import datetime
from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

class ProductBrain(Base):
    __tablename__ = "product_brains"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), default="Default product")
    product_description: Mapped[str] = mapped_column(Text)
    markets: Mapped[list] = mapped_column(JSON, default=list)
    problems_solved: Mapped[list] = mapped_column(JSON, default=list)
    target_buyers: Mapped[list] = mapped_column(JSON, default=list)
    differentiators: Mapped[list] = mapped_column(JSON, default=list)
    proof_points: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class OpportunityRun(Base):
    __tablename__ = "opportunity_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_url: Mapped[str] = mapped_column(String(500))
    company: Mapped[str] = mapped_column(String(250), default="Unknown")
    product_brain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_json: Mapped[dict] = mapped_column(JSON)
    response_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40), default="analyzed")
    feedback: Mapped[str | None] = mapped_column(String(40), nullable=True)
    feedback_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(40), default="queued")
    stage: Mapped[str] = mapped_column(String(80), default="Queued")
    request_json: Mapped[dict] = mapped_column(JSON)
    response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
