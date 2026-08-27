from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.models import OpportunityRun, ProductBrain
from app.schemas.opportunity import OpportunityRequest, OpportunityResponse, FeedbackInput
from app.services.research import research_company
from app.services.analyst import analyze

router = APIRouter(prefix="/opportunities", tags=["opportunities"])

@router.post("/analyze", response_model=OpportunityResponse)
async def analyze_opportunity(req: OpportunityRequest, db: Session = Depends(get_db)):
    try:
        product = db.get(ProductBrain, req.product_brain_id) if req.product_brain_id else None
        if not product and not req.seller_product:
            raise HTTPException(400, "Provide seller_product or product_brain_id")
        docs = await research_company(str(req.company_url))
        if not docs:
            raise RuntimeError("No usable research sources were found")
        product_context = None
        if product:
            product_context = {
                "name": product.name, "product_description": product.product_description,
                "markets": product.markets, "problems_solved": product.problems_solved,
                "target_buyers": product.target_buyers, "differentiators": product.differentiators,
                "proof_points": product.proof_points,
            }
        result = analyze(req, docs, product_context)
        run = OpportunityRun(
            company_url=str(req.company_url), company=result.company,
            product_brain_id=req.product_brain_id, request_json=req.model_dump(mode="json"),
            response_json=result.model_dump(mode="json"),
        )
        db.add(run); db.commit()
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@router.get("/runs")
def list_runs(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    rows = db.scalars(select(OpportunityRun).order_by(OpportunityRun.created_at.desc()).limit(limit)).all()
    return [{
        "id": x.id, "company": x.company, "company_url": x.company_url,
        "score": x.response_json.get("opportunity_score"), "confidence": x.response_json.get("confidence"),
        "why_now": x.response_json.get("why_now"), "feedback": x.feedback,
        "created_at": x.created_at.isoformat(), "response": x.response_json,
    } for x in rows]

@router.post("/runs/{run_id}/feedback")
def set_feedback(run_id: int, req: FeedbackInput, db: Session = Depends(get_db)):
    x = db.get(OpportunityRun, run_id)
    if not x: raise HTTPException(404, "Analysis run not found")
    x.feedback = req.feedback; x.feedback_note = req.note
    db.commit()
    return {"ok": True, "id": x.id, "feedback": x.feedback}
