from pydantic import BaseModel, Field
from typing import List, Optional

class ProductBrainInput(BaseModel):
    name: str = "Default product"
    product_description: str = Field(min_length=5)
    markets: List[str] = []
    problems_solved: List[str] = []
    target_buyers: List[str] = []
    differentiators: List[str] = []
    proof_points: List[str] = []

class ProductBrainResponse(ProductBrainInput):
    id: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
