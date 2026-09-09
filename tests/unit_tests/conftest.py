"""Offline API fixtures: SQLite instead of Postgres, a list instead of Redis."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import api.db as db_module
from api.models import Base


class FakeQueue:
    """In-memory stand-in for the Redis queue."""

    def __init__(self):
        self.pending: list[str] = []
        self.processing: list[str] = []

    async def enqueue(self, job_id):
        self.pending.insert(0, job_id)

    async def claim(self, timeout=5):
        if not self.pending:
            return None
        job_id = self.pending.pop()
        self.processing.append(job_id)
        return job_id

    async def release(self, job_id):
        if job_id in self.processing:
            self.processing.remove(job_id)

    async def requeue(self, job_id):
        await self.release(job_id)
        await self.enqueue(job_id)


@pytest_asyncio.fixture
async def db(tmp_path):
    """A fresh SQLite database wired into the module-level engine.

    File-backed, not `:memory:`: an in-memory SQLite is shared through a single
    pooled connection, so two sessions would see each other's uncommitted rows
    and no test could tell a flush from a commit.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    db_module._engine, db_module._sessionmaker = engine, sessionmaker
    yield sessionmaker
    db_module._engine, db_module._sessionmaker = None, None
    await engine.dispose()


@pytest.fixture
def fake_queue(monkeypatch):
    """Replace the Redis queue everywhere it is used."""
    import api.queue as queue_module
    import api.services as services_module

    queue = FakeQueue()
    for module in (queue_module, services_module.queue):
        monkeypatch.setattr(module, "enqueue", queue.enqueue, raising=False)
        monkeypatch.setattr(module, "claim", queue.claim, raising=False)
        monkeypatch.setattr(module, "release", queue.release, raising=False)
        monkeypatch.setattr(module, "requeue", queue.requeue, raising=False)
    return queue


@pytest.fixture
def stub_elasticsearch(monkeypatch):
    """Stop delete endpoints from reaching a real cluster."""
    import api.services as services_module

    deleted = {"sources": [], "collections": []}

    async def fake_source(collection, source):
        deleted["sources"].append(source.locator)
        return 1

    async def fake_collection(collection):
        deleted["collections"].append(collection.slug)
        return 1

    monkeypatch.setattr(services_module, "delete_source_chunks", fake_source)
    monkeypatch.setattr(services_module, "delete_collection_chunks", fake_collection)
    return deleted


@pytest_asyncio.fixture
async def client(db, fake_queue, stub_elasticsearch):
    """An HTTP client bound to the app, with infrastructure stubbed."""
    from api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest_asyncio.fixture
async def collection(client):
    """A created collection to hang sources and threads off."""
    response = await client.post(
        "/collections", json={"slug": "distsys", "name": "Distributed Systems"}
    )
    assert response.status_code == 201
    return response.json()
