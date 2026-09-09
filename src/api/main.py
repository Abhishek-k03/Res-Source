"""FastAPI application.

The API owns collections, sources, jobs, and conversations. It never ingests
inline: adding a source queues a job and returns 202.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from api import queue
from api.db import dispose_db, get_sessionmaker, init_db
from api.routers import collections, sources, threads
from api.schemas import HealthOut
from api.settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create tables on start and release connections on stop."""
    load_dotenv()
    await init_db()
    yield
    await queue.close_redis()
    await dispose_db()


app = FastAPI(
    title="Research RAG Agent",
    version="0.2.0",
    description="Multi-step LangGraph research over your own corpora.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(collections.router)
app.include_router(sources.router)
app.include_router(threads.router)


@app.get("/health", response_model=HealthOut, tags=["health"])
async def health() -> HealthOut:
    """Report whether Postgres and Redis are reachable."""
    database, redis_up, depth = False, False, 0
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        database = True
    except Exception:
        logger.warning("Database health check failed.", exc_info=True)
    try:
        await queue.get_redis().ping()
        depth = await queue.queue_depth()
        redis_up = True
    except Exception:
        logger.warning("Redis health check failed.", exc_info=True)

    return HealthOut(
        status="ok" if database and redis_up else "degraded",
        database=database,
        redis=redis_up,
        queue_depth=depth,
    )
