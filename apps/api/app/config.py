from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://localhost/chargegrid"
    migration_database_url: str | None = None
    supabase_url: str = "https://example.supabase.co"
    supabase_anon_key: str = ""
    cors_origins: list[str] = []
    # Environment variables supplied by Vercel or the shell take precedence over
    # this optional local-development file.
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")


@lru_cache
def settings():
    return Settings()
