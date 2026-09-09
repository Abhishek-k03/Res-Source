"""Persistent state: collections, their sources, ingestion jobs, and conversations.

Elasticsearch holds vectors; Postgres holds everything the product needs to be
able to list, resume, or undo. A collection's slug is what scopes retrieval, so
these rows are the authority on which collections exist.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """Declarative base for every table."""

    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class JobStatus(str, enum.Enum):
    """Lifecycle of an ingestion job."""

    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class SourceKind(str, enum.Enum):
    """Which loader a source needs."""

    files = "files"
    arxiv = "arxiv"
    urls = "urls"


class Collection(Base):
    """An isolated corpus. Its slug is the collection_id used to scope retrieval."""

    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    research_domain: Mapped[str] = mapped_column(
        String(300), default="the indexed research corpus"
    )
    index_name: Mapped[str] = mapped_column(String(100), default="research_agent")
    embedding_model: Mapped[str] = mapped_column(
        String(120), default="fastembed/BAAI/bge-small-en-v1.5"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    sources: Mapped[list[Source]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )
    threads: Mapped[list[Thread]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )


class Source(Base):
    """One ingestible thing: an uploaded file, an arXiv query, or a URL."""

    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("collection_id", "kind", "locator", name="uq_source_locator"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind, native_enum=False))
    locator: Mapped[str] = mapped_column(Text)
    """File path, URL, or arXiv query. Unique per collection, so re-adding is a no-op."""
    title: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False), default=JobStatus.pending
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    collection: Mapped[Collection] = relationship(back_populates="sources")
    jobs: Mapped[list[IngestionJob]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class IngestionJob(Base):
    """One attempt to ingest a source. Postgres is the authority on job state."""

    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    collection_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False), default=JobStatus.pending, index=True
    )
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    """Coarse progress for the UI: queued, loading, splitting, indexing, done."""
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    pruned_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source: Mapped[Source] = relationship(back_populates="jobs")


class Thread(Base):
    """A research conversation scoped to one collection."""

    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    collection: Mapped[Collection] = relationship(back_populates="threads")
    messages: Mapped[list[Message]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    """One turn. Assistant turns keep the plan, citations, and evidence verdict."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    plan: Mapped[list[Any]] = mapped_column(JSON, default=list)
    citations: Mapped[list[Any]] = mapped_column(JSON, default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    thread: Mapped[Thread] = relationship(back_populates="messages")
