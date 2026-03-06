from pydantic import BaseModel
import os


class Settings(BaseModel):
    environment: str = os.getenv("ENVIRONMENT", "local")
    app_base_url: str = os.getenv("APP_BASE_URL", "http://localhost:3000")
    cors_allowed_origins: str = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    database_url: str = os.getenv("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    card_cache_backend: str = os.getenv("CARD_CACHE_BACKEND", "sqlite")
    card_cache_db: str = os.getenv("CARD_CACHE_DB", "./data/cards.db")
    scryfall_bulk_path: str = os.getenv("SCRYFALL_BULK_PATH", "./data/scryfall-oracle-cards.json")
    rules_cache_dir: str = os.getenv("RULES_CACHE_DIR", "./data/rules")
    sentry_dsn: str = os.getenv("SENTRY_DSN", "")
    max_request_bytes: int = int(os.getenv("MAX_REQUEST_BYTES", "5242880"))
    trusted_hosts: str = os.getenv("TRUSTED_HOSTS", "localhost,127.0.0.1,api")
    force_https: bool = os.getenv("FORCE_HTTPS", "0").lower() in {"1", "true", "yes", "on"}
    sim_inline_fallback_no_worker: bool = os.getenv("SIM_INLINE_FALLBACK_NO_WORKER", "1").lower() in {"1", "true", "yes", "on"}
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    ai_enabled: bool = os.getenv("AI_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
    ai_timeout_s: float = float(os.getenv("AI_TIMEOUT_S", "6.0"))
    ai_max_output_tokens: int = int(os.getenv("AI_MAX_OUTPUT_TOKENS", "1200"))
    ai_cache_ttl_s: int = int(os.getenv("AI_CACHE_TTL_S", "86400"))
    ai_hide_unverifiable: bool = os.getenv("AI_HIDE_UNVERIFIABLE", "1").lower() in {"1", "true", "yes", "on"}
    ai_daily_budget_usd: float = float(os.getenv("AI_DAILY_BUDGET_USD", "0"))


settings = Settings()
