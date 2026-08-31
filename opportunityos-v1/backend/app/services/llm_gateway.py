import json
from typing import Any, Type

import httpx
from pydantic import BaseModel

from app.core.config import settings


SYSTEM = """You are Scalee OpportunityOS Universal Discovery.
Understand what a B2B seller offers, derive a category-agnostic buying-signal taxonomy, discover and rank accounts using only supplied evidence, and identify the three most relevant buyer roles.
Never claim private purchase intent. A high score means strong observable evidence of a likely buying window, not certainty that a company is buying.
Every signal must be grounded in supplied source material. 95+ is rare and requires multiple recent independent high-confidence signals.
Return JSON matching the supplied schema."""


def _schema_instruction(name: str, schema_model: Type[BaseModel]) -> str:
    schema = schema_model.model_json_schema()
    return (
        f"Return only valid JSON for schema name '{name}'. Do not use markdown fences. "
        f"The JSON must satisfy this schema exactly: {json.dumps(schema)}"
    )


def _messages(name: str, schema_model: Type[BaseModel], payload: dict) -> tuple[str, str]:
    system = f"{SYSTEM}\n\n{_schema_instruction(name, schema_model)}"
    user = json.dumps(payload, default=str)
    return system, user


def _parse_json_text(schema_model: Type[BaseModel], text: str):
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].lstrip()
    return schema_model.model_validate_json(cleaned)


def _gemini_json(name: str, schema_model: Type[BaseModel], payload: dict):
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    system, user = _messages(name, schema_model, payload)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema_model.model_json_schema(),
        },
    }
    with httpx.Client(timeout=90) as client:
        response = client.post(url, params={"key": settings.gemini_api_key}, json=body)
        response.raise_for_status()
        data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    text = "".join(str(part.get("text") or "") for part in parts)
    return _parse_json_text(schema_model, text)


def _anthropic_json(name: str, schema_model: Type[BaseModel], payload: dict):
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    system, user = _messages(name, schema_model, payload)
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": settings.anthropic_model,
        "max_tokens": 5000,
        "temperature": 0.1,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    with httpx.Client(timeout=90) as client:
        response = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
        response.raise_for_status()
        data = response.json()
    blocks = data.get("content") or []
    text = "".join(str(block.get("text") or "") for block in blocks if block.get("type") == "text")
    return _parse_json_text(schema_model, text)


def _openai_json(name: str, schema_model: Type[BaseModel], payload: dict):
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    schema = schema_model.model_json_schema()
    result = client.responses.create(
        model=settings.openai_model,
        input=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(payload, default=str)},
        ],
        text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": False}},
    )
    return schema_model.model_validate_json(result.output_text)


def generate_structured(name: str, schema_model: Type[BaseModel], payload: dict):
    providers = [p.strip().lower() for p in settings.llm_provider_order.split(",") if p.strip()]
    errors: list[str] = []
    for provider in providers:
        try:
            if provider == "gemini":
                result = _gemini_json(name, schema_model, payload)
            elif provider == "anthropic":
                result = _anthropic_json(name, schema_model, payload)
            elif provider == "openai":
                result = _openai_json(name, schema_model, payload)
            else:
                errors.append(f"{provider}: unsupported provider")
                continue
            print(f"LLM provider={provider} task={name} status=success", flush=True)
            return result
        except Exception as exc:
            errors.append(f"{provider}: {type(exc).__name__}: {str(exc)[:300]}")
            print(f"LLM provider={provider} task={name} status=failed error={type(exc).__name__}", flush=True)
    raise RuntimeError("All configured LLM providers failed: " + " | ".join(errors))
