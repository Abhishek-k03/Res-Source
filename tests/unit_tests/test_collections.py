import pytest
from langchain_core.documents import Document

from ingest_graph.graph import chunk_id, split_documents
from ingest_graph.state import IngestState
from shared.configuration import BaseConfiguration
from shared.retrieval import (
    COLLECTION_KEY,
    _reject_unscoped,
    collection_filter,
    scoped_search_kwargs,
)


def test_no_collection_means_no_filter():
    assert collection_filter(None) == []
    assert collection_filter("") == []


def test_collection_filter_matches_the_metadata_field_exactly():
    assert collection_filter("distsys") == [
        {"term": {f"metadata.{COLLECTION_KEY}.keyword": "distsys"}}
    ]


def test_scoping_preserves_the_configured_search_arguments():
    config = BaseConfiguration(search_kwargs={"k": 7}, collection_id="ml")

    kwargs = scoped_search_kwargs(config)

    assert kwargs["k"] == 7
    assert kwargs["filter"] == collection_filter("ml")


def test_scoping_appends_to_a_caller_supplied_filter():
    config = BaseConfiguration(
        search_kwargs={"k": 5, "filter": [{"term": {"metadata.year": 2024}}]},
        collection_id="ml",
    )

    assert scoped_search_kwargs(config)["filter"] == [
        {"term": {"metadata.year": 2024}},
        *collection_filter("ml"),
    ]


def test_unscoped_search_kwargs_are_untouched():
    config = BaseConfiguration(search_kwargs={"k": 5})
    assert scoped_search_kwargs(config) == {"k": 5}


def test_a_backend_without_filter_support_refuses_rather_than_leaks():
    with pytest.raises(NotImplementedError):
        _reject_unscoped(BaseConfiguration(collection_id="ml"))
    _reject_unscoped(BaseConfiguration())  # unscoped is fine


def test_the_same_document_in_two_collections_is_two_chunks():
    a = Document(page_content="body", metadata={"source": "s", COLLECTION_KEY: "ml"})
    b = Document(page_content="body", metadata={"source": "s", COLLECTION_KEY: "os"})
    assert chunk_id(a) != chunk_id(b)


def test_an_unscoped_chunk_id_is_unchanged_by_the_collection_feature():
    # Guards idempotency for indexes built before collections existed.
    plain = Document(page_content="body", metadata={"source": "s"})
    empty = Document(page_content="body", metadata={"source": "s", COLLECTION_KEY: ""})
    assert chunk_id(plain) == chunk_id(empty)


async def test_chunks_are_stamped_with_the_collection_being_ingested():
    state = IngestState(docs=[Document(page_content="x" * 1500)])
    config = {"configurable": {"collection_id": "distsys"}}

    chunks = (await split_documents(state, config=config))["chunks"]

    assert chunks
    assert all(c.metadata[COLLECTION_KEY] == "distsys" for c in chunks)


async def test_chunks_are_unstamped_when_no_collection_is_configured():
    state = IngestState(docs=[Document(page_content="x" * 1500)])

    chunks = (await split_documents(state, config={"configurable": {}}))["chunks"]

    assert all(COLLECTION_KEY not in c.metadata for c in chunks)
