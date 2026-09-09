"""Runtime settings for the API and the worker."""

from __future__ import annotations

from functools import lru_cache

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

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings."""
    return Settings()
