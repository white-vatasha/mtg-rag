from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "app.db"


class Settings(BaseSettings):
    secret_key: str = "change-me-in-production-use-env"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    database_url: str = f"sqlite:///{DEFAULT_DB}"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_llm_model: str = "llama3.2:3b"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_llm_num_ctx: int = 4096
    ollama_request_timeout: float = 300.0
    auto_index_on_startup: bool = True
    auto_download_cards: bool = False
    atomic_cards_url: str = "https://mtgjson.com/api/v5/AtomicCards.json"
    ollama_wait_seconds: float = 300.0
    index_decks_on_startup: bool = True

    # Datadog (logging, APM, DogStatsD). Enable when an agent is reachable.
    dd_trace_enabled: bool = False
    dd_metrics_enabled: bool = False
    dd_logs_json: bool = True
    dd_logs_injection: bool = True
    dd_service: str = "mtg-rag-api"
    dd_env: str = "development"
    dd_version: str = "0.1.0"
    dd_agent_host: str = "127.0.0.1"
    dd_trace_agent_port: int = 8126
    dd_dogstatsd_port: int = 8125
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
