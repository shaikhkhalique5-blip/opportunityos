from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.models import ProductBrain
from app.schemas.product import ProductBrainInput, ProductBrainResponse

router = APIRouter(prefix="/products", tags=["products"])

def serialize(x: ProductBrain) -> ProductBrainResponse:
    return ProductBrainResponse(
        id=x.id, name=x.name, product_description=x.product_description,
        markets=x.markets or [], problems_solved=x.problems_solved or [],
        target_buyers=x.target_buyers or [], differentiators=x.differentiators or [],
        proof_points=x.proof_points or [], created_at=x.created_at.isoformat() if x.created_at else None,
        updated_at=x.updated_at.isoformat() if x.updated_at else None,
    )

@router.get("", response_model=list[ProductBrainResponse])
def list_products(db: Session = Depends(get_db)):
    return [serialize(x) for x in db.scalars(select(ProductBrain).order_by(ProductBrain.updated_at.desc())).all()]

@router.post("", response_model=ProductBrainResponse)
def create_product(req: ProductBrainInput, db: Session = Depends(get_db)):
    x = ProductBrain(**req.model_dump())
    db.add(x); db.commit(); db.refresh(x)
    return serialize(x)

@router.put("/{product_id}", response_model=ProductBrainResponse)
def update_product(product_id: int, req: ProductBrainInput, db: Session = Depends(get_db)):
    x = db.get(ProductBrain, product_id)
    if not x: raise HTTPException(404, "Product Brain not found")
    for k, v in req.model_dump().items(): setattr(x, k, v)
    db.commit(); db.refresh(x)
    return serialize(x)
