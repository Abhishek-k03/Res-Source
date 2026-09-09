"""Ingestion job lifecycle: state transitions, retries, and recovery."""

from datetime import datetime, timedelta, timezone
from importlib import import_module

import pytest
import pytest_asyncio
from sqlalchemy import select

from api import services
from api.models import Collection, IngestionJob, JobStatus, Source, SourceKind

# The package exports the compiled graph as `graph`, shadowing the submodule.
ingest_module = import_module("ingest_graph.graph")


class _GraphStub:
    """Stands in for the compiled ingest graph, node by node as it streams."""

    def __init__(self, result=None, error=None):
        self.result, self.error = result or {}, error
        self.calls = []

    async def astream(self, state, config, stream_mode="updates"):
        self.calls.append((state, config))
        if self.error:
            raise self.error
        indexed = int(self.result.get("indexed_count", 0))
        yield {"load_documents": {"docs": [None] * indexed}}
        yield {"split_documents": {"chunks": [None] * indexed}}
        yield {"index_documents": {"indexed_count": indexed}}
        yield {
            "prune_stale_chunks": {"pruned_count": self.result.get("pruned_count", 0)}
        }


@pytest.fixture
def stub_ingest(monkeypatch):
    def install(result=None, error=None):
        graph = _GraphStub(result, error)
        monkeypatch.setattr(ingest_module, "graph", graph)
        return graph

    return install


@pytest_asyncio.fixture
async def seeded(db):
    """A collection with one queued source and job."""
    async with db() as session:
        collection = Collection(slug="distsys", name="Distributed Systems")
        session.add(collection)
        await session.flush()
        source = Source(
            collection_id=collection.id, kind=SourceKind.arxiv, locator="raft"
        )
        session.add(source)
        await session.flush()
        job = IngestionJob(
            source_id=source.id, collection_id=collection.id, max_attempts=2
        )
        session.add(job)
        await session.commit()
        return {"collection": collection.id, "source": source.id, "job": job.id}


async def test_a_successful_job_completes_and_records_counts(db, seeded, stub_ingest):
    stub_ingest(result={"indexed_count": 12, "pruned_count": 3})

    async with db() as session:
        job = await services.run_job(session, seeded["job"])

    assert job.status is JobStatus.completed
    assert job.stage == "done"
    assert (job.chunk_count, job.pruned_count) == (12, 3)
    assert job.attempts == 1
    assert job.started_at is not None and job.finished_at is not None

    async with db() as session:
        source = await session.get(Source, seeded["source"])
    assert source.status is JobStatus.completed
    assert source.chunk_count == 12


async def test_the_collection_scopes_the_ingestion_run(db, seeded, stub_ingest):
    graph = stub_ingest(result={"indexed_count": 1})

    async with db() as session:
        await services.run_job(session, seeded["job"])

    state, config = graph.calls[0]
    assert state == {"source": "arxiv", "query": "raft"}
    assert config["configurable"]["collection_id"] == "distsys"


async def test_indexing_nothing_is_a_failure_not_a_success(db, seeded, stub_ingest):
    stub_ingest(result={"indexed_count": 0})

    async with db() as session:
        job = await services.run_job(session, seeded["job"])

    assert job.status is JobStatus.failed
    assert "No readable content" in job.error


async def test_a_failure_below_the_attempt_limit_is_retried(
    db, seeded, stub_ingest, fake_queue
):
    stub_ingest(error=RuntimeError("network down"))

    async with db() as session:
        job = await services.run_job(session, seeded["job"])

    assert job.status is JobStatus.pending
    assert job.attempts == 1
    assert "network down" in job.error
    assert fake_queue.pending == [seeded["job"]]


async def test_exhausting_the_attempt_limit_fails_the_source(
    db, seeded, stub_ingest, fake_queue
):
    stub_ingest(error=RuntimeError("network down"))
    await fake_queue.enqueue(seeded["job"])

    # Drive it the way the worker does: claim, run, release.
    for _ in range(2):
        job_id = await fake_queue.claim()
        assert job_id == seeded["job"]
        async with db() as session:
            job = await services.run_job(session, job_id)
        await fake_queue.release(job_id)

    assert job.status is JobStatus.failed
    assert job.attempts == 2
    assert fake_queue.pending == []  # no third attempt was queued

    async with db() as session:
        source = await session.get(Source, seeded["source"])
    assert source.status is JobStatus.failed
    assert "network down" in source.error


async def test_a_finished_job_is_not_run_again(db, seeded, stub_ingest):
    graph = stub_ingest(result={"indexed_count": 5})

    async with db() as session:
        await services.run_job(session, seeded["job"])
    async with db() as session:
        await services.run_job(session, seeded["job"])

    assert len(graph.calls) == 1


async def test_deleting_a_source_cancels_its_queued_jobs(db, seeded, stub_ingest):
    # The job row goes with the source, so a queued id becomes a safe no-op.
    graph = stub_ingest(result={"indexed_count": 5})
    async with db() as session:
        source = await session.get(Source, seeded["source"])
        await session.delete(source)
        await session.commit()

    async with db() as session:
        assert await services.run_job(session, seeded["job"]) is None

    assert graph.calls == []


async def test_an_unknown_job_id_is_a_no_op(db, stub_ingest):
    stub_ingest(result={"indexed_count": 1})
    async with db() as session:
        assert await services.run_job(session, "does-not-exist") is None


async def test_a_job_abandoned_mid_run_is_requeued(db, seeded, fake_queue):
    async with db() as session:
        job = await session.get(IngestionJob, seeded["job"])
        job.status = JobStatus.processing
        job.started_at = datetime.now(timezone.utc) - timedelta(hours=2)
        await session.commit()

    async with db() as session:
        requeued = await services.requeue_stale_jobs(session)
        await session.commit()

    assert requeued == 1
    assert fake_queue.pending == [seeded["job"]]
    async with db() as session:
        job = await session.get(IngestionJob, seeded["job"])
    assert job.status is JobStatus.pending


async def test_a_job_still_being_worked_on_is_left_alone(db, seeded, fake_queue):
    async with db() as session:
        job = await session.get(IngestionJob, seeded["job"])
        job.status = JobStatus.processing
        job.started_at = datetime.now(timezone.utc)
        await session.commit()

    async with db() as session:
        assert await services.requeue_stale_jobs(session) == 0
    assert fake_queue.pending == []


async def test_a_pending_job_whose_signal_was_lost_is_requeued(db, seeded, fake_queue):
    async with db() as session:
        job = await session.get(IngestionJob, seeded["job"])
        job.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        await session.commit()

    async with db() as session:
        assert await services.requeue_stale_jobs(session) == 1
    assert fake_queue.pending == [seeded["job"]]


async def test_a_freshly_queued_job_is_not_requeued(db, seeded, fake_queue):
    # It is waiting its turn behind other work, not lost.
    async with db() as session:
        assert await services.requeue_stale_jobs(session) == 0
    assert fake_queue.pending == []


async def test_a_job_reports_each_stage_as_it_runs(db, seeded, stub_ingest):
    # A frontend needs more than "processing" for a long ingestion.
    stub_ingest(result={"indexed_count": 4})
    seen = []

    async with db() as session:
        job = await session.get(IngestionJob, seeded["job"])
        original_commit = session.commit

        async def recording_commit():
            seen.append(job.stage)
            await original_commit()

        session.commit = recording_commit
        await services.run_job(session, seeded["job"])

    assert seen[:1] == ["loading"]
    assert ["splitting", "indexing", "pruning"] == [
        s for s in seen if s in ("splitting", "indexing", "pruning")
    ]


async def test_a_job_is_committed_before_its_id_is_published(db, seeded, monkeypatch):
    """A worker that claims the id must be able to find the row.

    Enqueuing inside the transaction lets a worker read the id before the row
    is durable, silently dropping the ingestion.
    """
    import api.services as services_module

    visible: list[bool] = []

    async def checking_enqueue(job_id):
        # A *separate* session, as the worker would use.
        async with db() as other:
            visible.append(await other.get(IngestionJob, job_id) is not None)

    monkeypatch.setattr(services_module.queue, "enqueue", checking_enqueue)

    async with db() as session:
        source = await session.get(Source, seeded["source"])
        await services.create_job(session, source)

    assert visible == [True], "the job id was published before it was committed"


async def test_the_worker_runs_several_jobs_at_once(db, fake_queue, monkeypatch):
    """Each job blocks until all three have started.

    A worker that runs jobs one at a time deadlocks here rather than passing.
    """
    import asyncio

    from api import worker as worker_module
    from api.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("WORKER_CONCURRENCY", "3")

    started = 0
    all_started = asyncio.Event()

    class _SlowGraph:
        async def astream(self, state, config, stream_mode="updates"):
            nonlocal started
            started += 1
            if started >= 3:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=5)
            yield {"index_documents": {"indexed_count": 1}}
            yield {"prune_stale_chunks": {"pruned_count": 0}}

    monkeypatch.setattr(ingest_module, "graph", _SlowGraph())

    async with db() as session:
        collection = Collection(slug="many", name="Many")
        session.add(collection)
        await session.flush()
        for i in range(3):
            source = Source(
                collection_id=collection.id,
                kind=SourceKind.urls,
                locator=f"https://{i}",
            )
            session.add(source)
            await session.flush()
            session.add(IngestionJob(source_id=source.id, collection_id=collection.id))
        await session.commit()

    async with db() as session:
        jobs = list(await session.scalars(select(IngestionJob)))
    for job in jobs:
        await fake_queue.enqueue(job.id)

    stop = asyncio.Event()
    runner = asyncio.create_task(worker_module.run(stop))
    try:
        await asyncio.wait_for(all_started.wait(), timeout=10)
    finally:
        stop.set()
        await asyncio.wait_for(runner, timeout=10)
    get_settings.cache_clear()

    assert started == 3
    async with db() as session:
        done = list(await session.scalars(select(IngestionJob)))
    assert all(j.status is JobStatus.completed for j in done)
