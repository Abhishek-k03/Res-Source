"""Work that is neither HTTP nor storage: running ingestion and research.

Kept out of the routers so the worker can call the same code without importing
FastAPI, and so the graph stays the only place that knows about LangGraph.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import queue
from api.models import Collection, IngestionJob, JobStatus, Source, SourceKind
from api.settings import get_settings

logger = logging.getLogger(__name__)

STAGE_AFTER_NODE = {
    "load_documents": "splitting",
    "split_documents": "indexing",
    "index_documents": "pruning",
    "prune_stale_chunks": "done",
}
"""What a job is doing once each ingest node has finished."""


def graph_config(collection: Collection, **overrides: Any) -> RunnableConfig:
    """Build the LangGraph config that scopes a run to one collection."""
    configurable: dict[str, Any] = {
        "index_name": collection.index_name,
        "collection_id": collection.slug,
        "embedding_model": collection.embedding_model,
        "research_domain": collection.research_domain,
    }
    configurable.update(overrides)
    return RunnableConfig(configurable=configurable)


async def create_job(
    session: AsyncSession, source: Source, *, enqueue: bool = True
) -> IngestionJob:
    """Queue an ingestion attempt for a source.

    The row is committed before its id reaches Redis. Publishing first lets a
    worker claim the id and find nothing -- the job is dropped and the source
    waits forever with no error to show for it.
    """
    settings = get_settings()
    job = IngestionJob(
        source_id=source.id,
        collection_id=source.collection_id,
        max_attempts=settings.job_max_attempts,
    )
    source.status = JobStatus.pending
    source.error = ""
    session.add(job)
    await session.commit()
    if enqueue:
        await queue.enqueue(job.id)
    return job


async def run_job(session: AsyncSession, job_id: str) -> IngestionJob | None:
    """Run one ingestion job to completion or failure.

    Returns None when the job no longer exists or is not runnable, so a stale
    queue message is a no-op rather than an error.
    """
    from ingest_graph.graph import graph as ingest_graph

    job = await session.get(IngestionJob, job_id)
    if job is None:
        logger.warning("Job %s no longer exists; dropping.", job_id)
        return None
    if job.status in (JobStatus.completed, JobStatus.failed):
        return job

    source = await session.get(Source, job.source_id)
    collection = await session.get(Collection, job.collection_id)
    if source is None or collection is None:
        job.status = JobStatus.failed
        job.error = "Source or collection was deleted before the job ran."
        job.finished_at = datetime.now(timezone.utc)
        return job

    job.status = JobStatus.processing
    job.attempts += 1
    job.stage = "loading"
    job.started_at = datetime.now(timezone.utc)
    source.status = JobStatus.processing
    await session.commit()

    state: dict[str, Any] = {"source": source.kind.value}
    config = graph_config(collection)
    configurable = config["configurable"]
    if source.kind is SourceKind.arxiv:
        state["query"] = source.locator
    elif source.kind is SourceKind.urls:
        state["urls"] = [source.locator]
    else:
        configurable["docs_dir"] = source.locator

    result: dict[str, Any] = {}
    try:
        # Streamed rather than awaited so the job reports real progress: an
        # ingestion is long enough that a single "processing" is not useful.
        async for chunk in ingest_graph.astream(  # type: ignore[call-overload]
            state, config, stream_mode="updates"
        ):
            for node, update in chunk.items():
                result.update(update or {})
                if node == "split_documents":
                    job.chunk_count = len(update.get("chunks") or [])
                stage = STAGE_AFTER_NODE.get(node)
                if stage:
                    job.stage = stage
                    await session.commit()
    except Exception as exc:
        logger.exception("Ingestion job %s failed.", job_id)
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        if job.attempts >= job.max_attempts:
            job.status = JobStatus.failed
            job.stage = "failed"
            source.status = JobStatus.failed
            source.error = job.error
        else:
            job.status = JobStatus.pending
            job.stage = "queued"
            source.status = JobStatus.pending
            await queue.requeue(job.id)
        await session.commit()
        return job

    indexed = int(result.get("indexed_count", 0))
    job.chunk_count = indexed
    job.pruned_count = int(result.get("pruned_count", 0))
    job.finished_at = datetime.now(timezone.utc)
    source.chunk_count = indexed

    if indexed == 0:
        # Nothing readable is a failed ingestion, not a successful empty one.
        job.status = JobStatus.failed
        job.stage = "failed"
        job.error = "No readable content was found at this source."
        source.status = JobStatus.failed
        source.error = job.error
    else:
        job.status = JobStatus.completed
        job.stage = "done"
        job.error = ""
        source.status = JobStatus.completed
        source.error = ""

    await session.commit()
    return job


def _as_utc(value: datetime | None) -> datetime | None:
    """Read a timestamp as UTC, whether or not the driver kept the timezone."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def requeue_stale_jobs(session: AsyncSession) -> int:
    """Return abandoned jobs to the queue.

    Covers a worker that died mid-job and a signal that was never delivered.
    Only jobs older than the stale threshold are touched: a job queued moments
    ago is waiting its turn, and requeueing it would have it run twice.
    """
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.job_stale_after_seconds
    )
    rows = await session.scalars(
        select(IngestionJob).where(
            IngestionJob.status.in_((JobStatus.pending, JobStatus.processing))
        )
    )
    requeued = 0
    for job in rows:
        if job.status is JobStatus.processing:
            started = _as_utc(job.started_at)
            if started is not None and started > cutoff:
                continue
            job.status = JobStatus.pending
            job.stage = "queued"
        else:
            created = _as_utc(job.created_at)
            if created is not None and created > cutoff:
                continue
        await queue.requeue(job.id)
        requeued += 1
    if requeued:
        logger.info("Requeued %d stale job(s).", requeued)
    return requeued


async def delete_source_chunks(collection: Collection, source: Source) -> int:
    """Remove a source's vectors from Elasticsearch."""
    from shared import retrieval
    from shared.retrieval import collection_filter

    config = graph_config(collection)
    query = {
        "bool": {
            "must": [{"term": {"metadata.source.keyword": source.locator}}],
            "filter": collection_filter(collection.slug),
        }
    }
    with retrieval.make_retriever(config) as retriever:
        client = retriever.vectorstore.client  # type: ignore[attr-defined]
        if not client.indices.exists(index=collection.index_name):
            return 0
        response = client.delete_by_query(
            index=collection.index_name,
            query=query,
            refresh=True,
            conflicts="proceed",
        )
    return int(response.get("deleted", 0))


def delete_uploaded_files(source: Source) -> bool:
    """Remove an uploaded source's files, if it has any.

    Only paths that resolve inside the upload directory are touched, so a
    locator that is an arXiv query or a URL can never name something to delete.
    """
    if source.kind is not SourceKind.files:
        return False

    upload_root = Path(get_settings().upload_dir).resolve()
    try:
        target = Path(source.locator).resolve()
        target.relative_to(upload_root)
    except (OSError, ValueError):
        return False

    if not target.is_dir():
        return False
    shutil.rmtree(target, ignore_errors=True)
    return True


async def delete_collection_chunks(collection: Collection) -> int:
    """Remove every vector belonging to a collection."""
    from shared import retrieval
    from shared.retrieval import collection_filter

    config = graph_config(collection)
    clauses = collection_filter(collection.slug)
    if not clauses:
        return 0
    with retrieval.make_retriever(config) as retriever:
        client = retriever.vectorstore.client  # type: ignore[attr-defined]
        if not client.indices.exists(index=collection.index_name):
            return 0
        response = client.delete_by_query(
            index=collection.index_name,
            query={"bool": {"filter": clauses}},
            refresh=True,
            conflicts="proceed",
        )
    return int(response.get("deleted", 0))


async def stream_research(
    collection: Collection, messages: list[dict[str, str]], **overrides: Any
) -> AsyncIterator[dict[str, Any]]:
    """Run the research graph, yielding progress events then a final answer.

    Only node-level milestones are emitted -- never raw model reasoning.
    """
    from retrieval_graph.graph import graph as research_graph
    from shared.utils import message_text

    config = graph_config(collection, **overrides)
    final: dict[str, Any] = {
        "content": "",
        "citations": [],
        "plan": [],
        "evidence": {},
    }

    async for chunk in research_graph.astream(
        {"messages": messages},
        config,
        stream_mode="updates",
    ):  # type: ignore[call-overload]
        for node, update in chunk.items():
            if node == "analyze_and_route_query":
                yield {"type": "routed", "route": update["router"]["type"]}
            elif node == "create_research_plan":
                final["plan"] = list(update["steps"])
                yield {"type": "plan", "steps": final["plan"]}
            elif node == "conduct_research":
                for done in update["completed_steps"]:
                    yield {
                        "type": "step_complete",
                        "step": done["step"],
                        "document_count": done["document_count"],
                    }
            elif node == "assess_evidence":
                final["evidence"] = dict(update["evidence"])
                yield {"type": "evidence", **final["evidence"]}

            if "messages" in update:
                final["content"] = message_text(update["messages"][-1])
            if update.get("citations") is not None:
                final["citations"] = list(update["citations"])

    yield {"type": "answer", **final}
