from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.opportunities import router as opportunities_router
from app.api.products import router as products_router
from app.core.db import Base, engine

app = FastAPI(title="Scalee OpportunityOS API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000","https://opportunityos-frontend-production.up.railway.app","https://app.scalee.in"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(opportunities_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0"}
