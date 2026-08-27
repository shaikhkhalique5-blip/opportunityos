from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_model: str = "gpt-5"
    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/opportunityos"
    tavily_api_key: str = ""
    research_max_pages: int = 8
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
