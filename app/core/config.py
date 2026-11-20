"""Application settings, read from environment variables (specs/operations.md §3)."""

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def normalize_database_url(url: str) -> str:
    """Use the psycopg 3 driver for plain `postgresql://` / `postgres://` URLs."""
    for prefix in ("postgresql://", "postgres://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["development", "production", "test"] = "development"
    # DB_URL is accepted for compatibility with the existing .env files.
    database_url: str = Field(validation_alias=AliasChoices("DATABASE_URL", "DB_URL"))
    app_url: str = "http://localhost:3000"
    log_level: str = "INFO"

    # Email (specs/auth.md §7). "console" only logs; use smtp (Mailpit) in dev, resend in prod.
    email_backend: Literal["console", "smtp", "resend"] = "console"
    email_from: str = "Be Rich <no-reply@localhost>"
    resend_api_key: str | None = None
    smtp_host: str = "localhost"
    smtp_port: int = 1025

    @field_validator("database_url")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_database_url(value)

    @property
    def cookie_secure(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
