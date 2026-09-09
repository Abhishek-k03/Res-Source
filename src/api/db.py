"""Database engine and session handling."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.models import Base
from api.settings import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide engine, creating it on first use."""
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the session factory bound to the engine."""
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def init_db() -> None:
    """Create any missing tables.

    Deliberately not a migration tool: the schema is small and versioned with
    the code. A deployment that must preserve data across schema changes would
    need Alembic here.
    """
    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    """Close pooled connections on shutdown."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine, _sessionmaker = None, None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional session for code outside a request, such as the worker."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session that commits on success.

    This commit runs when the dependency is torn down, which FastAPI does
    *after* the response has been sent. A handler that mutates must therefore
    commit itself, or a client that re-reads immediately races the commit and
    sees the old state. `commit_now` is that call.
    """
    async with session_scope() as session:
        yield session


async def commit_now(session: AsyncSession) -> None:
    """Make a handler's changes durable before its response is sent."""
    await session.commit()
