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


settings = Settings()
