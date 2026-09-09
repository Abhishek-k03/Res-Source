"""Runtime settings for the API and the worker."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Infrastructure endpoints and job policy, overridable from the environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://research:changeme@localhost:5434/research_agent"
    )
    redis_url: str = "redis://localhost:6380/0"

    upload_dir: str = "data/uploads"
    """Where uploaded files are stored. Their path becomes the source locator."""

    job_queue_key: str = "research_agent:jobs"
    job_processing_key: str = "research_agent:jobs:processing"
    job_max_attempts: int = 3
    worker_concurrency: int = 3
    """How many ingestion jobs one worker runs at once."""
    job_stale_after_seconds: int = 900
    """A job left in `processing` for longer than this is treated as abandoned."""

    retriever_provider: str = "elastic-local"
    """Vector store backing retrieval. Managed Elasticsearch wants 'elastic'."""

    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, value: str) -> str:
        """Force the asyncpg driver.

        Hosted Postgres hands out `postgresql://`, which SQLAlchemy resolves to
        psycopg and then fails on, since the engine is async.
        """
        if value.startswith("postgres://"):
            value = value.replace("postgres://", "postgresql://", 1)
        if value.startswith("postgresql://"):
            value = value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated list, which is what a dashboard field gives."""
        if isinstance(value, str) and not value.strip().startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings."""
    return Settings()
