from io import BytesIO

from fastapi import APIRouter, File, HTTPException, UploadFile
from pypdf import PdfReader
from pptx import Presentation

from app.schemas.discovery import DiscoveryRequest, DiscoveryResponse
from app.services.discovery import push_to_amplemarket
from app.services.discovery_amplemarket import run_discovery

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.post("/run", response_model=DiscoveryResponse)
async def discover(req: DiscoveryRequest):
    try:
        return await run_discovery(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/deck")
async def ingest_deck(file: UploadFile = File(...)):
    try:
        raw = await file.read()
        name = (file.filename or "deck").lower()
        if len(raw) > 15 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Deck must be 15 MB or smaller")
        if name.endswith(".pdf"):
            reader = PdfReader(BytesIO(raw))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        elif name.endswith(".pptx"):
            deck = Presentation(BytesIO(raw))
            parts = []
            for slide in deck.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text:
                        parts.append(shape.text)
            text = "\n".join(parts)
        elif name.endswith((".txt", ".md")):
            text = raw.decode("utf-8", errors="ignore")
        else:
            raise HTTPException(status_code=415, detail="Upload PDF, PPTX, TXT, or MD")
        text = text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="No readable text found in deck")
        return {"filename": file.filename, "text": text[:60000], "characters": len(text)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse deck: {exc}") from exc


@router.post("/amplemarket")
async def amplemarket_handoff(payload: dict):
    try:
        return await push_to_amplemarket(payload)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
