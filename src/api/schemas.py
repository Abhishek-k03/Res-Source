"""Request and response bodies."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.models import JobStatus, SourceKind

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")


class CollectionCreate(BaseModel):
    """Create a collection. The slug is what scopes retrieval, so it is immutable."""

    slug: str
    name: str = ""
    description: str = ""
    research_domain: str = "the indexed research corpus"
    index_name: str = "research_agent"
    embedding_model: str = "fastembed/BAAI/bge-small-en-v1.5"

    @field_validator("slug")
    @classmethod
    def _valid_slug(cls, value: str) -> str:
        value = value.strip().lower()
        if not _SLUG.match(value):
            raise ValueError(
                "slug must be 2-63 characters of lowercase letters, digits, - or _"
            )
        return value


class CollectionOut(BaseModel):
    """A collection as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    description: str
    research_domain: str
    index_name: str
    embedding_model: str
    created_at: datetime
    source_count: int = 0


class SourceCreate(BaseModel):
    """Add an arXiv query or a URL. Files are added through the upload endpoint."""

    kind: SourceKind
    locator: str = Field(min_length=1)
    title: str = ""

    @field_validator("kind")
    @classmethod
    def _not_a_file(cls, value: SourceKind) -> SourceKind:
        if value is SourceKind.files:
            raise ValueError("upload files via POST /collections/{id}/sources/upload")
        return value


class SourceOut(BaseModel):
    """A source and the outcome of its most recent ingestion."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    collection_id: str
    kind: SourceKind
    locator: str
    title: str
    status: JobStatus
    chunk_count: int
    error: str
    created_at: datetime
    updated_at: datetime
    latest_job: JobOut | None = None
    """Most recent ingestion attempt, so a list view can show live progress."""


class JobOut(BaseModel):
    """Ingestion job state."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    collection_id: str
    status: JobStatus
    stage: str
    attempts: int
    max_attempts: int
    chunk_count: int
    pruned_count: int
    error: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SourceAccepted(BaseModel):
    """What the API returns when it queues work instead of doing it."""

    source: SourceOut
    job: JobOut


class ThreadCreate(BaseModel):
    """Start a conversation in a collection."""

    title: str = "New conversation"


class ThreadOut(BaseModel):
    """A research conversation."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    collection_id: str
    title: str
    created_at: datetime


class MessageOut(BaseModel):
    """One turn of a conversation."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    thread_id: str
    role: str
    content: str
    plan: list[Any]
    citations: list[Any]
    evidence: dict[str, Any]
    created_at: datetime


class AskRequest(BaseModel):
    """Ask a question in a thread."""

    question: str = Field(min_length=1)
    max_research_steps: int | None = Field(default=None, ge=1, le=10)
    k: int | None = Field(default=None, ge=1, le=50)


class HealthOut(BaseModel):
    """Liveness of the API and its dependencies."""

    status: str
    database: bool
    redis: bool
    queue_depth: int
