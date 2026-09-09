"""End-to-end checks that need real infrastructure.

Elasticsearch tests skip unless the cluster in docker-compose.yml is reachable;
the agent test additionally skips without a GOOGLE_API_KEY. Run them with:

    docker compose up -d
    python -m pytest tests/integration_tests -v
"""

import os
import uuid

import pytest
from dotenv import load_dotenv
from langchain_core.documents import Document

from ingest_graph.graph import graph as ingest_graph
from retrieval_graph.graph import graph as research_graph
from shared import retrieval
from shared.utils import message_text

load_dotenv()

pytestmark = pytest.mark.integration

CORPUS = [
    Document(
        page_content=(
            "Reciprocal rank fusion merges several ranked result lists by scoring each "
            "document as the sum of one over a constant plus its rank in each list. It "
            "needs no score calibration between the lists it merges."
        ),
        metadata={"title": "Reciprocal Rank Fusion", "source": "test://rrf"},
    ),
    Document(
        page_content=(
            "Chunk overlap repeats a fixed number of characters between neighbouring "
            "chunks so that a sentence split across a boundary still appears whole in "
            "at least one chunk."
        ),
        metadata={"title": "Chunking Strategies", "source": "test://chunking"},
    ),
]


def _elasticsearch_is_up() -> bool:
    import urllib.error
    import urllib.request

    url = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
    try:
        with urllib.request.urlopen(f"{url}/_cluster/health", timeout=3) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


needs_elasticsearch = pytest.mark.skipif(
    not _elasticsearch_is_up(),
    reason="Elasticsearch is not running (docker compose up -d)",
)
needs_llm = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"), reason="GROQ_API_KEY is not set"
)


@pytest.fixture
def index_config():
    """Give each test a throwaway index so runs cannot contaminate each other."""
    config = {"configurable": {"index_name": f"test_{uuid.uuid4().hex[:12]}"}}
    yield config
    with retrieval.make_retriever(config) as retriever:
        retriever.vectorstore.client.indices.delete(
            index=config["configurable"]["index_name"], ignore_unavailable=True
        )


@needs_elasticsearch
async def test_ingested_documents_are_retrievable(index_config):
    result = await ingest_graph.ainvoke({"docs": CORPUS}, index_config)
    assert result["indexed_count"] >= len(CORPUS)

    with retrieval.make_retriever(index_config) as retriever:
        retriever.vectorstore.client.indices.refresh(
            index=index_config["configurable"]["index_name"]
        )
        hits = await retriever.ainvoke("how are ranked lists combined?")

    assert hits, "expected at least one hit"
    assert any("rank fusion" in doc.page_content.lower() for doc in hits)


@needs_elasticsearch
async def test_re_ingesting_updates_instead_of_duplicating(index_config):
    first = await ingest_graph.ainvoke({"docs": CORPUS}, index_config)
    await ingest_graph.ainvoke({"docs": CORPUS}, index_config)

    with retrieval.make_retriever(index_config) as retriever:
        client = retriever.vectorstore.client
        index = index_config["configurable"]["index_name"]
        client.indices.refresh(index=index)
        stored = client.count(index=index)["count"]

    assert stored == first["indexed_count"]


@needs_elasticsearch
async def test_local_files_are_loaded_chunked_and_indexed(tmp_path, index_config):
    (tmp_path / "note.md").write_text("# Note\n" + "content. " * 400, encoding="utf-8")
    index_config["configurable"]["docs_dir"] = str(tmp_path)

    result = await ingest_graph.ainvoke({"source": "files"}, index_config)

    assert result["indexed_count"] > 1  # long enough to have been split


@needs_elasticsearch
@needs_llm
async def test_agent_answers_from_the_corpus_with_citations(index_config):
    await ingest_graph.ainvoke({"docs": CORPUS}, index_config)
    with retrieval.make_retriever(index_config) as retriever:
        retriever.vectorstore.client.indices.refresh(
            index=index_config["configurable"]["index_name"]
        )

    index_config["configurable"]["research_domain"] = (
        "retrieval and chunking techniques"
    )
    result = await research_graph.ainvoke(
        {"messages": [{"role": "user", "content": "Why use overlap between chunks?"}]},
        index_config,
    )

    answer = message_text(result["messages"][-1])
    assert result["router"]["type"] == "research"
    assert result["documents"], "the agent should have retrieved something"
    assert "[1]" in answer, "citation markers should be normalised to ASCII"
    assert result["citations"], "the answer should carry resolved citations"
    assert all(c["resolved"] for c in result["citations"])


def _count(config, **kwargs):
    with retrieval.make_retriever(config) as retriever:
        client = retriever.vectorstore.client
        index = config["configurable"]["index_name"]
        client.indices.refresh(index=index)
        return client.count(index=index, **kwargs)["count"]


@needs_elasticsearch
async def test_collections_share_an_index_without_seeing_each_other(index_config):
    ml = {"configurable": {**index_config["configurable"], "collection_id": "ml"}}
    os_ = {"configurable": {**index_config["configurable"], "collection_id": "os"}}

    await ingest_graph.ainvoke({"docs": [CORPUS[0]]}, ml)
    await ingest_graph.ainvoke({"docs": [CORPUS[1]]}, os_)

    assert _count(index_config) == 2  # one index

    with retrieval.make_retriever(ml) as retriever:
        retriever.vectorstore.client.indices.refresh(
            index=index_config["configurable"]["index_name"]
        )
        hits = await retriever.ainvoke("chunk overlap between neighbouring chunks")

    assert hits, "expected a hit inside the collection"
    assert all(d.metadata["collection_id"] == "ml" for d in hits)
    assert not any("overlap" in d.page_content.lower() for d in hits)


@needs_elasticsearch
async def test_the_same_document_can_live_in_two_collections(index_config):
    for collection in ("ml", "os"):
        await ingest_graph.ainvoke(
            {"docs": [CORPUS[0]]},
            {
                "configurable": {
                    **index_config["configurable"],
                    "collection_id": collection,
                }
            },
        )

    assert _count(index_config) == 2


@needs_elasticsearch
async def test_editing_a_source_leaves_no_stale_chunks(index_config):
    original = Document(
        page_content="The original text about consensus algorithms.",
        metadata={"title": "Note", "source": "test://note"},
    )
    edited = Document(
        page_content="Completely rewritten text about vector clocks.",
        metadata={"title": "Note", "source": "test://note"},
    )

    await ingest_graph.ainvoke({"docs": [original]}, index_config)
    result = await ingest_graph.ainvoke({"docs": [edited]}, index_config)

    assert result["pruned_count"] == 1
    assert _count(index_config) == 1
    assert _count(index_config, query={"match": {"text": "consensus"}}) == 0


@needs_elasticsearch
async def test_pruning_leaves_other_sources_alone(index_config):
    await ingest_graph.ainvoke({"docs": CORPUS}, index_config)
    before = _count(index_config)

    edited = Document(
        page_content="Rank fusion, rewritten.",
        metadata={"title": "Reciprocal Rank Fusion", "source": "test://rrf"},
    )
    await ingest_graph.ainvoke({"docs": [edited]}, index_config)

    assert _count(index_config) == before  # one replaced, one untouched
    assert _count(index_config, query={"match": {"text": "chunk overlap"}}) > 0
