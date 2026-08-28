from fastapi import APIRouter, HTTPException

from app.schemas.discovery import DiscoveryRequest, DiscoveryResponse
from app.services.discovery import push_to_amplemarket, run_discovery

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.post("/run", response_model=DiscoveryResponse)
async def discover(req: DiscoveryRequest):
    try:
        return await run_discovery(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/amplemarket")
async def amplemarket_handoff(payload: dict):
    try:
        return await push_to_amplemarket(payload)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
