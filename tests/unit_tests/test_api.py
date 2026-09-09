"""API behaviour: collections, source lifecycle, job state, and conversations."""

import json
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.models import JobStatus, SourceKind


async def test_creating_and_listing_collections(client):
    listed = (await client.get("/collections")).json()
    assert listed == []

    created = await client.post("/collections", json={"slug": "ml", "name": "ML"})
    assert created.status_code == 201
    assert created.json()["slug"] == "ml"

    listed = (await client.get("/collections")).json()
    assert [c["slug"] for c in listed] == ["ml"]


async def test_a_slug_cannot_be_reused(client, collection):
    again = await client.post("/collections", json={"slug": "distsys"})
    assert again.status_code == 409


@pytest.mark.parametrize("slug", ["", "A", "has space", "x" * 70, "-leading"])
async def test_invalid_slugs_are_rejected(client, slug):
    assert (await client.post("/collections", json={"slug": slug})).status_code == 422


async def test_a_collection_is_reachable_by_slug_or_id(client, collection):
    by_id = await client.get(f"/collections/{collection['id']}")
    by_slug = await client.get("/collections/distsys")
    assert by_id.json()["id"] == by_slug.json()["id"] == collection["id"]


async def test_unknown_collection_is_404(client):
    assert (await client.get("/collections/nope")).status_code == 404


async def test_adding_a_source_queues_work_instead_of_doing_it(
    client, collection, fake_queue
):
    response = await client.post(
        f"/collections/{collection['id']}/sources",
        json={"kind": "arxiv", "locator": "raft consensus"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["source"]["status"] == JobStatus.pending.value
    assert body["job"]["status"] == JobStatus.pending.value
    assert body["job"]["stage"] == "queued"
    assert fake_queue.pending == [body["job"]["id"]]


async def test_re_adding_the_same_locator_reuses_the_source(client, collection):
    payload = {"kind": "urls", "locator": "https://example.com/a"}
    first = (
        await client.post(f"/collections/{collection['id']}/sources", json=payload)
    ).json()
    second = (
        await client.post(f"/collections/{collection['id']}/sources", json=payload)
    ).json()

    assert first["source"]["id"] == second["source"]["id"]
    assert first["job"]["id"] != second["job"]["id"]  # but it is re-ingested
    sources = (await client.get(f"/collections/{collection['id']}/sources")).json()
    assert len(sources) == 1


async def test_the_same_locator_in_two_collections_is_two_sources(client, collection):
    other = (await client.post("/collections", json={"slug": "ml"})).json()
    payload = {"kind": "urls", "locator": "https://example.com/a"}

    a = (
        await client.post(f"/collections/{collection['id']}/sources", json=payload)
    ).json()
    b = (await client.post(f"/collections/{other['id']}/sources", json=payload)).json()

    assert a["source"]["id"] != b["source"]["id"]


async def test_files_must_be_uploaded_not_declared(client, collection):
    response = await client.post(
        f"/collections/{collection['id']}/sources",
        json={"kind": "files", "locator": "/etc/passwd"},
    )
    assert response.status_code == 422


async def test_uploading_a_document_queues_it(
    client, collection, tmp_path, monkeypatch
):
    from api.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

    response = await client.post(
        f"/collections/{collection['id']}/sources/upload",
        files={"file": ("raft.md", b"# Raft\nLeader election.", "text/markdown")},
    )
    get_settings.cache_clear()

    assert response.status_code == 202
    body = response.json()
    assert body["source"]["kind"] == SourceKind.files.value
    assert body["source"]["title"] == "raft.md"
    assert (tmp_path / "distsys").exists()


async def test_an_unsupported_upload_is_refused(client, collection):
    response = await client.post(
        f"/collections/{collection['id']}/sources/upload",
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 415


async def test_a_traversing_filename_cannot_escape_the_upload_directory(
    client, collection, tmp_path, monkeypatch
):
    from api.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

    response = await client.post(
        f"/collections/{collection['id']}/sources/upload",
        files={"file": ("../../../evil.md", b"x", "text/markdown")},
    )
    get_settings.cache_clear()

    assert response.status_code == 202
    locator = response.json()["source"]["locator"]
    assert str(tmp_path) in locator
    assert "evil.md" in response.json()["source"]["title"]
    assert not (tmp_path.parent.parent / "evil.md").exists()


async def test_reindexing_creates_a_second_job(client, collection, fake_queue):
    added = (
        await client.post(
            f"/collections/{collection['id']}/sources",
            json={"kind": "arxiv", "locator": "raft"},
        )
    ).json()
    source_id = added["source"]["id"]

    again = await client.post(f"/sources/{source_id}/reindex")

    assert again.status_code == 202
    jobs = (await client.get(f"/sources/{source_id}/jobs")).json()
    assert len(jobs) == 2
    assert len(fake_queue.pending) == 2


async def test_deleting_a_source_removes_its_chunks(
    client, collection, stub_elasticsearch
):
    added = (
        await client.post(
            f"/collections/{collection['id']}/sources",
            json={"kind": "urls", "locator": "https://example.com/a"},
        )
    ).json()

    deleted = await client.delete(f"/sources/{added['source']['id']}")

    assert deleted.status_code == 204
    assert stub_elasticsearch["sources"] == ["https://example.com/a"]
    assert (await client.get(f"/collections/{collection['id']}/sources")).json() == []


async def test_deleting_a_collection_removes_its_vectors_and_rows(
    client, collection, stub_elasticsearch
):
    await client.post(
        f"/collections/{collection['id']}/sources",
        json={"kind": "urls", "locator": "https://example.com/a"},
    )

    deleted = await client.delete(f"/collections/{collection['id']}")

    assert deleted.status_code == 204
    assert stub_elasticsearch["collections"] == ["distsys"]
    assert (await client.get("/collections")).json() == []


async def test_job_status_is_pollable(client, collection):
    added = (
        await client.post(
            f"/collections/{collection['id']}/sources",
            json={"kind": "arxiv", "locator": "raft"},
        )
    ).json()

    job = (await client.get(f"/jobs/{added['job']['id']}")).json()

    assert job["id"] == added["job"]["id"]
    assert job["attempts"] == 0
    assert job["max_attempts"] == 3


async def test_unknown_job_is_404(client):
    assert (await client.get("/jobs/missing")).status_code == 404


async def test_source_count_is_reported_on_the_collection(client, collection):
    for locator in ("https://a", "https://b"):
        await client.post(
            f"/collections/{collection['id']}/sources",
            json={"kind": "urls", "locator": locator},
        )

    assert (await client.get(f"/collections/{collection['id']}")).json()[
        "source_count"
    ] == 2
    assert (await client.get("/collections")).json()[0]["source_count"] == 2


# --- conversations ---------------------------------------------------------


def _events(text: str) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.fixture
def stub_research(monkeypatch):
    """Replace the research graph with a fixed sequence of events."""
    import api.services as services_module

    def install(events):
        async def fake_stream(collection, messages, **overrides):
            fake_stream.seen = {"messages": messages, "overrides": overrides}
            for event in events:
                yield event

        fake_stream.seen = {}
        monkeypatch.setattr(services_module, "stream_research", fake_stream)
        return fake_stream

    return install


ANSWER = {
    "type": "answer",
    "content": "Raft elects a leader [1].",
    "citations": [
        {
            "number": 1,
            "title": "Raft",
            "source": "raft.pdf",
            "url": "",
            "resolved": True,
        }
    ],
    "plan": ["how does leader election work"],
    "evidence": {"sufficient": True, "reason": "covered", "missing": ""},
}


async def test_asking_streams_progress_then_the_answer(
    client, collection, stub_research
):
    stub_research(
        [
            {"type": "routed", "route": "research"},
            {"type": "plan", "steps": ["how does leader election work"]},
            {
                "type": "step_complete",
                "step": "how does leader election work",
                "document_count": 4,
            },
            {
                "type": "evidence",
                "sufficient": True,
                "reason": "covered",
                "missing": "",
            },
            ANSWER,
        ]
    )
    thread = (
        await client.post(f"/collections/{collection['id']}/threads", json={})
    ).json()

    response = await client.post(
        f"/threads/{thread['id']}/ask",
        json={"question": "How does leader election work?"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    kinds = [e["type"] for e in _events(response.text)]
    assert kinds == ["routed", "plan", "step_complete", "evidence", "answer", "done"]


async def test_the_answer_is_persisted_with_its_citations(
    client, collection, stub_research
):
    stub_research([ANSWER])
    thread = (
        await client.post(f"/collections/{collection['id']}/threads", json={})
    ).json()

    await client.post(f"/threads/{thread['id']}/ask", json={"question": "How?"})
    messages = (await client.get(f"/threads/{thread['id']}/messages")).json()

    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "Raft elects a leader [1]."
    assert messages[1]["citations"][0]["title"] == "Raft"
    assert messages[1]["evidence"]["sufficient"] is True
    assert messages[1]["plan"] == ["how does leader election work"]


async def test_a_follow_up_carries_the_earlier_turns(client, collection, stub_research):
    stream = stub_research([ANSWER])
    thread = (
        await client.post(f"/collections/{collection['id']}/threads", json={})
    ).json()

    await client.post(f"/threads/{thread['id']}/ask", json={"question": "First?"})
    await client.post(f"/threads/{thread['id']}/ask", json={"question": "Second?"})

    sent = stream.seen["messages"]
    assert [m["content"] for m in sent] == [
        "First?",
        "Raft elects a leader [1].",
        "Second?",
    ]


async def test_the_first_question_titles_the_thread(client, collection, stub_research):
    stub_research([ANSWER])
    thread = (
        await client.post(f"/collections/{collection['id']}/threads", json={})
    ).json()

    await client.post(
        f"/threads/{thread['id']}/ask", json={"question": "How does Raft vote?"}
    )

    threads = (await client.get(f"/collections/{collection['id']}/threads")).json()
    assert threads[0]["title"] == "How does Raft vote?"


async def test_research_budget_overrides_reach_the_graph(
    client, collection, stub_research
):
    stream = stub_research([ANSWER])
    thread = (
        await client.post(f"/collections/{collection['id']}/threads", json={})
    ).json()

    await client.post(
        f"/threads/{thread['id']}/ask",
        json={"question": "How?", "max_research_steps": 2, "k": 9},
    )

    assert stream.seen["overrides"] == {
        "max_research_steps": 2,
        "search_kwargs": {"k": 9},
    }


async def test_a_failing_run_reports_an_error_event_and_saves_nothing(
    client, collection, monkeypatch
):
    import api.services as services_module

    async def exploding(collection, messages, **overrides):
        raise RuntimeError("model unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr(services_module, "stream_research", exploding)
    thread = (
        await client.post(f"/collections/{collection['id']}/threads", json={})
    ).json()

    response = await client.post(
        f"/threads/{thread['id']}/ask", json={"question": "How?"}
    )

    events = _events(response.text)
    assert events[-1]["type"] == "error"
    assert "model unavailable" in events[-1]["message"]
    messages = (await client.get(f"/threads/{thread['id']}/messages")).json()
    assert [m["role"] for m in messages] == ["user"]


async def test_asking_in_an_unknown_thread_is_404(client):
    assert (
        await client.post("/threads/nope/ask", json={"question": "x"})
    ).status_code == 404


async def test_deleting_a_thread_removes_its_messages(
    client, collection, stub_research
):
    stub_research([ANSWER])
    thread = (
        await client.post(f"/collections/{collection['id']}/threads", json={})
    ).json()
    await client.post(f"/threads/{thread['id']}/ask", json={"question": "How?"})

    assert (await client.delete(f"/threads/{thread['id']}")).status_code == 204
    assert (await client.get(f"/threads/{thread['id']}/messages")).status_code == 404


async def test_threads_are_scoped_to_their_collection(client, collection):
    other = (await client.post("/collections", json={"slug": "ml"})).json()
    await client.post(f"/collections/{collection['id']}/threads", json={"title": "A"})
    await client.post(f"/collections/{other['id']}/threads", json={"title": "B"})

    mine = (await client.get(f"/collections/{collection['id']}/threads")).json()
    assert [t["title"] for t in mine] == ["A"]


async def test_deleting_an_uploaded_source_removes_its_files(
    client, collection, tmp_path, monkeypatch
):
    from api.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    added = (
        await client.post(
            f"/collections/{collection['id']}/sources/upload",
            files={"file": ("raft.md", b"# Raft", "text/markdown")},
        )
    ).json()
    stored = Path(added["source"]["locator"])
    assert stored.is_dir()

    await client.delete(f"/sources/{added['source']['id']}")
    get_settings.cache_clear()

    assert not stored.exists()


async def test_deleting_a_non_file_source_touches_no_files(
    client, collection, tmp_path, monkeypatch
):
    from api import services
    from api.models import Source, SourceKind
    from api.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    outside = tmp_path / "keep_me"
    outside.mkdir()

    # A locator that names a real directory, but is not a file source.
    assert (
        services.delete_uploaded_files(
            Source(collection_id="x", kind=SourceKind.urls, locator=str(outside))
        )
        is False
    )
    get_settings.cache_clear()
    assert outside.exists()


async def test_a_file_source_outside_the_upload_directory_is_not_deleted(
    tmp_path, monkeypatch
):
    from api import services
    from api.models import Source, SourceKind
    from api.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir()
    elsewhere = tmp_path / "important"
    elsewhere.mkdir()

    assert (
        services.delete_uploaded_files(
            Source(collection_id="x", kind=SourceKind.files, locator=str(elsewhere))
        )
        is False
    )
    get_settings.cache_clear()
    assert elsewhere.exists()


# --- mutations must be durable before the response is sent -----------------


@pytest_asyncio.fixture
async def no_teardown_commit_client(db, fake_queue, stub_elasticsearch):
    """A client whose session never commits on teardown.

    FastAPI tears a yield-dependency down *after* sending the response, so a
    handler that leans on that commit returns 204 while the row is still there
    -- a client re-reading immediately sees the old state. Removing the
    teardown commit makes any such handler fail here.
    """
    from api.db import get_session
    from api.main import app

    async def session_without_teardown_commit():
        async with db() as session:
            yield session

    app.dependency_overrides[get_session] = session_without_teardown_commit
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def test_creating_a_collection_is_durable_immediately(
    no_teardown_commit_client,
):
    client = no_teardown_commit_client
    await client.post("/collections", json={"slug": "durable"})
    assert [c["slug"] for c in (await client.get("/collections")).json()] == ["durable"]


async def test_deleting_a_collection_is_durable_immediately(
    no_teardown_commit_client,
):
    client = no_teardown_commit_client
    created = (await client.post("/collections", json={"slug": "gone"})).json()

    await client.delete(f"/collections/{created['id']}")

    assert (await client.get("/collections")).json() == []


async def test_source_and_thread_mutations_are_durable_immediately(
    no_teardown_commit_client,
):
    client = no_teardown_commit_client
    collection = (await client.post("/collections", json={"slug": "cc"})).json()

    added = (
        await client.post(
            f"/collections/{collection['id']}/sources",
            json={"kind": "urls", "locator": "https://example.com"},
        )
    ).json()
    assert (
        len((await client.get(f"/collections/{collection['id']}/sources")).json()) == 1
    )

    thread = (
        await client.post(f"/collections/{collection['id']}/threads", json={})
    ).json()
    assert (
        len((await client.get(f"/collections/{collection['id']}/threads")).json()) == 1
    )

    await client.delete(f"/sources/{added['source']['id']}")
    assert (await client.get(f"/collections/{collection['id']}/sources")).json() == []

    await client.delete(f"/threads/{thread['id']}")
    assert (await client.get(f"/collections/{collection['id']}/threads")).json() == []
