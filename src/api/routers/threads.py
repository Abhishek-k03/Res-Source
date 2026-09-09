"""Research conversations, streamed as server-sent events."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import services
from api.db import commit_now, get_session, session_scope
from api.models import Collection, Message, Thread
from api.routers.collections import load_collection
from api.schemas import AskRequest, MessageOut, ThreadCreate, ThreadOut

logger = logging.getLogger(__name__)

router = APIRouter(tags=["threads"])


async def _load_thread(session: AsyncSession, thread_id: str) -> Thread:
    thread = await session.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    return thread


@router.post(
    "/collections/{collection_id}/threads",
    response_model=ThreadOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_thread(
    collection_id: str,
    body: ThreadCreate,
    session: AsyncSession = Depends(get_session),
) -> ThreadOut:
    """Start a conversation in a collection."""
    collection = await load_collection(collection_id, session)
    thread = Thread(collection_id=collection.id, title=body.title)
    session.add(thread)
    await commit_now(session)
    return ThreadOut.model_validate(thread)


@router.get("/collections/{collection_id}/threads", response_model=list[ThreadOut])
async def list_threads(
    collection_id: str, session: AsyncSession = Depends(get_session)
) -> list[ThreadOut]:
    """List a collection's conversations."""
    collection = await load_collection(collection_id, session)
    rows = await session.scalars(
        select(Thread)
        .where(Thread.collection_id == collection.id)
        .order_by(Thread.created_at.desc())
    )
    return [ThreadOut.model_validate(row) for row in rows]


@router.get("/threads/{thread_id}/messages", response_model=list[MessageOut])
async def list_messages(
    thread_id: str, session: AsyncSession = Depends(get_session)
) -> list[MessageOut]:
    """Replay a conversation."""
    await _load_thread(session, thread_id)
    rows = await session.scalars(
        select(Message)
        .where(Message.thread_id == thread_id)
        .order_by(Message.created_at)
    )
    return [MessageOut.model_validate(row) for row in rows]


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _history(session: AsyncSession, thread_id: str) -> list[dict[str, str]]:
    """Prior turns, so a follow-up question can refer to what was already asked."""
    rows = await session.scalars(
        select(Message)
        .where(Message.thread_id == thread_id)
        .order_by(Message.created_at)
    )
    return [{"role": m.role, "content": m.content} for m in rows]


@router.post("/threads/{thread_id}/ask")
async def ask(
    thread_id: str, body: AskRequest, session: AsyncSession = Depends(get_session)
) -> StreamingResponse:
    """Research a question, streaming workflow progress then the cited answer.

    The graph is run inside its own session: the streaming body outlives this
    request's transaction, so it cannot share it.
    """
    thread = await _load_thread(session, thread_id)
    collection = await session.get(Collection, thread.collection_id)
    if collection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collection not found")

    history = await _history(session, thread_id)
    session.add(Message(thread_id=thread_id, role="user", content=body.question))
    if len(history) == 0:
        thread.title = body.question[:120]
    await session.commit()

    messages = history + [{"role": "user", "content": body.question}]
    overrides: dict[str, Any] = {}
    if body.max_research_steps is not None:
        overrides["max_research_steps"] = body.max_research_steps
    if body.k is not None:
        overrides["search_kwargs"] = {"k": body.k}
    collection_id = collection.id

    async def events() -> AsyncIterator[str]:
        answer: dict[str, Any] | None = None
        try:
            async with session_scope() as run_session:
                run_collection = await run_session.get(Collection, collection_id)
                assert run_collection is not None
                async for event in services.stream_research(
                    run_collection, messages, **overrides
                ):
                    if event["type"] == "answer":
                        answer = event
                    yield _sse(event)
        except Exception as exc:
            logger.exception("Research failed for thread %s", thread_id)
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            return

        if answer is not None:
            async with session_scope() as save_session:
                save_session.add(
                    Message(
                        thread_id=thread_id,
                        role="assistant",
                        content=answer["content"],
                        plan=answer["plan"],
                        citations=answer["citations"],
                        evidence=answer["evidence"],
                    )
                )
        yield _sse({"type": "done"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    """Delete a conversation and its messages."""
    thread = await _load_thread(session, thread_id)
    await session.delete(thread)
    await commit_now(session)
