"""Compatibility shim for the previous OpenAI client surface.

OpportunityOS now routes structured-generation tasks to Gemini first and
Anthropic second. Existing service code can keep calling OpenAI(...).responses.create
while we finish removing the old provider-specific function names.
"""

import json
from types import SimpleNamespace

import httpx

from app.core.config import settings


class _Responses:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def _gemini(self, *, model: str, input: list[dict], text: dict):
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        schema = (((text or {}).get("format") or {}).get("schema") or {})
        system = "\n".join(str(x.get("content") or "") for x in input if x.get("role") == "system")
        user = "\n".join(str(x.get("content") or "") for x in input if x.get("role") == "user")
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
        with httpx.Client(timeout=90) as client:
            response = client.post(url, params={"key": settings.gemini_api_key}, json=body)
            response.raise_for_status()
            data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Gemini returned no candidates")
        parts = ((candidates[0].get("content") or {}).get("parts") or [])
        output_text = "".join(str(part.get("text") or "") for part in parts)
        if not output_text.strip():
            raise RuntimeError("Gemini returned empty output")
        return SimpleNamespace(output_text=output_text)

    def _anthropic(self, *, input: list[dict], text: dict):
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")
        schema = (((text or {}).get("format") or {}).get("schema") or {})
        system = "\n".join(str(x.get("content") or "") for x in input if x.get("role") == "system")
        user = "\n".join(str(x.get("content") or "") for x in input if x.get("role") == "user")
        user += "\n\nReturn only valid JSON matching this schema exactly: " + json.dumps(schema)
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
        output_text = "".join(str(block.get("text") or "") for block in blocks if block.get("type") == "text")
        cleaned = output_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].lstrip()
        if not cleaned:
            raise RuntimeError("Anthropic returned empty output")
        return SimpleNamespace(output_text=cleaned)

    def create(self, *, model: str, input: list[dict], text: dict, **kwargs):
        errors = []
        providers = [p.strip().lower() for p in settings.llm_provider_order.split(",") if p.strip()]
        for provider in providers:
            try:
                if provider == "gemini":
                    result = self._gemini(model=model, input=input, text=text)
                elif provider == "anthropic":
                    result = self._anthropic(input=input, text=text)
                else:
                    continue
                print(f"LLM provider={provider} status=success", flush=True)
                return result
            except Exception as exc:
                errors.append(f"{provider}: {type(exc).__name__}: {str(exc)[:250]}")
                print(f"LLM provider={provider} status=failed error={type(exc).__name__}", flush=True)
        raise RuntimeError("All configured LLM providers failed: " + " | ".join(errors))


class OpenAI:
    def __init__(self, api_key: str = "", **kwargs):
        self.responses = _Responses(api_key=api_key)
