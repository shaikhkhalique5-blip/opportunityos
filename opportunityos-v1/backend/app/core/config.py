from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Vendor-independent LLM routing. Gemini is primary, Anthropic is fallback.
    llm_provider_order: str = "gemini,anthropic,openai"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # OpenAI remains optional as a migration / emergency fallback only.
    openai_api_key: str = ""
    openai_model: str = "gpt-5"

    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/opportunityos"
    tavily_api_key: str = ""
    research_max_pages: int = 8

    # Universal Discovery providers. The engine degrades gracefully when optional keys are absent.
    apollo_api_key: str = ""
    clay_api_key: str = ""
    clay_webhook_url: str = ""
    amplemarket_api_key: str = ""
    amplemarket_webhook_url: str = ""
    discovery_max_candidates: int = 100

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
