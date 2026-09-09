import pytest
from langchain_core.documents import Document

from ingest_graph.graph import chunk_id, split_documents
from ingest_graph.graph import graph as ingest_graph
from ingest_graph.state import IngestState
from retrieval_graph.graph import graph as research_graph
from retrieval_graph.graph import (
    research_in_parallel,
    route_after_assessment,
    route_query,
)
from retrieval_graph.researcher_graph.graph import graph as researcher_graph
from retrieval_graph.state import AgentState, EvidenceAssessment, Router


def test_graphs_compile_with_expected_nodes():
    assert {
        "load_documents",
        "split_documents",
        "index_documents",
        "prune_stale_chunks",
    } <= set(ingest_graph.get_graph().nodes)
    assert {
        "analyze_and_route_query",
        "create_research_plan",
        "conduct_research",
        "assess_evidence",
        "abstain",
        "respond",
    } <= set(research_graph.get_graph().nodes)
    assert {"generate_queries", "retrieve_documents"} <= set(
        researcher_graph.get_graph().nodes
    )


@pytest.mark.parametrize(
    ("router_type", "expected"),
    [
        ("research", "create_research_plan"),
        ("more-info", "ask_for_more_info"),
        ("general", "respond_to_general_query"),
    ],
)
def test_route_query_maps_each_classification(router_type, expected):
    state = AgentState(messages=[], router=Router(type=router_type, logic=""))
    assert route_query(state) == expected


def test_route_query_rejects_unknown_classification():
    state = AgentState(messages=[], router={"type": "nonsense", "logic": ""})
    with pytest.raises(ValueError):
        route_query(state)


def test_every_plan_step_is_dispatched_as_its_own_task():
    sends = research_in_parallel(AgentState(messages=[], steps=["a", "b", "c"]))

    assert [s.node for s in sends] == ["conduct_research"] * 3
    assert [s.arg.step for s in sends] == ["a", "b", "c"]


@pytest.mark.parametrize(
    ("sufficient", "expected"), [(True, "respond"), (False, "abstain")]
)
def test_assessment_gates_answering(sufficient, expected):
    state = AgentState(
        messages=[],
        evidence=EvidenceAssessment(sufficient=sufficient, reason="", missing=""),
    )
    assert route_after_assessment(state) == expected


async def test_split_documents_chunks_with_overlap_and_keeps_metadata():
    state = IngestState(
        docs=[Document(page_content="x" * 2500, metadata={"title": "long.txt"})]
    )
    config = {"configurable": {"chunk_size": 1000, "chunk_overlap": 200}}

    chunks = (await split_documents(state, config=config))["chunks"]

    assert len(chunks) > 1
    assert all(len(c.page_content) <= 1000 for c in chunks)
    assert all(c.metadata["title"] == "long.txt" for c in chunks)


def test_chunk_id_is_stable_for_the_same_content_and_source():
    doc = Document(page_content="body", metadata={"source": "a", "start_index": 0})
    same = Document(page_content="body", metadata={"source": "a", "start_index": 99})
    assert chunk_id(doc) == chunk_id(same)


def test_chunk_id_distinguishes_content_and_source():
    a = Document(page_content="body", metadata={"source": "a"})
    b = Document(page_content="body", metadata={"source": "b"})
    c = Document(page_content="other", metadata={"source": "a"})
    assert len({chunk_id(a), chunk_id(b), chunk_id(c)}) == 3


async def test_split_documents_handles_an_empty_corpus():
    result = await split_documents(IngestState(), config={"configurable": {}})
    assert result == {"chunks": []}
