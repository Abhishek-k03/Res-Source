"""End-to-end tests of the agent's control flow, with the model and the vector
store stubbed out. These run offline: no GOOGLE_API_KEY, no Elasticsearch."""

import asyncio
from contextlib import contextmanager
from importlib import import_module
from unittest.mock import patch

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

import shared.retrieval as retrieval_module
from retrieval_graph.graph import graph as research_graph

# The package exports the compiled graph as `graph`, shadowing the submodule of
# the same name, so reach the modules explicitly to patch symbols inside them.
agent_module = import_module("retrieval_graph.graph")
researcher_module = import_module("retrieval_graph.researcher_graph.graph")

CORPUS = [
    Document(
        page_content="Overlap keeps split sentences whole.",
        metadata={"title": "Chunking"},
    ),
    Document(
        page_content="Rank fusion merges ranked lists.", metadata={"title": "Fusion"}
    ),
]


class _StructuredStub:
    """Stands in for `model.with_structured_output(Schema)`."""

    def __init__(self, value):
        self._value = value

    async def ainvoke(self, messages):
        return self._value


class _ModelStub:
    """Returns canned structured output per schema, and canned prose otherwise."""

    def __init__(self, by_schema, text):
        self._by_schema = by_schema
        self._text = text
        self.structured_calls: list[str] = []
        self.methods: list[str] = []

    def with_structured_output(self, schema, *, method="function_calling"):
        name = getattr(schema, "__name__", str(schema))
        self.structured_calls.append(name)
        self.methods.append(method)
        return _StructuredStub(self._by_schema[name])

    async def ainvoke(self, messages):
        return AIMessage(content=self._text)


@pytest.fixture
def stub_agent(monkeypatch):
    """Patch the model loader and the retriever; return the model stub to configure."""

    def install(
        router_type="research",
        steps=("what is overlap?",),
        queries=("overlap",),
        text="final answer",
        sufficient=True,
        corpus=CORPUS,
    ):
        model = _ModelStub(
            {
                "Router": {"type": router_type, "logic": "because"},
                "Plan": {"steps": list(steps)},
                "SearchQueries": {"queries": list(queries)},
                "EvidenceAssessment": {
                    "sufficient": sufficient,
                    "reason": "checked",
                    "missing": "" if sufficient else "a paper about overlap",
                },
            },
            text,
        )
        monkeypatch.setattr(agent_module, "load_chat_model", lambda _name: model)
        monkeypatch.setattr(researcher_module, "load_chat_model", lambda _name: model)

        class _Retriever:
            async def ainvoke(self, query, config=None):
                return list(corpus)

        @contextmanager
        def fake_make_retriever(config):
            yield _Retriever()

        monkeypatch.setattr(retrieval_module, "make_retriever", fake_make_retriever)
        return model

    return install


async def test_research_route_plans_retrieves_and_answers(stub_agent):
    stub_agent(router_type="research", steps=("step one", "step two"))

    result = await research_graph.ainvoke(
        {"messages": [{"role": "user", "content": "why overlap chunks?"}]}
    )

    assert result["router"]["type"] == "research"
    assert result["steps"] == ["step one", "step two"]  # the plan is kept
    assert {s["step"] for s in result["completed_steps"]} == {"step one", "step two"}
    assert result["messages"][-1].content == "final answer"


async def test_documents_are_deduplicated_across_steps_and_queries(stub_agent):
    # Two steps x two queries, all returning the same two documents.
    stub_agent(steps=("a", "b"), queries=("q1", "q2"))

    result = await research_graph.ainvoke(
        {"messages": [{"role": "user", "content": "why overlap chunks?"}]}
    )

    assert len(result["documents"]) == len(CORPUS)


@pytest.mark.parametrize("router_type", ["general", "more-info"])
async def test_non_research_routes_answer_without_retrieving(stub_agent, router_type):
    model = stub_agent(router_type=router_type, text="clarifying reply")

    result = await research_graph.ainvoke(
        {"messages": [{"role": "user", "content": "hello"}]}
    )

    assert result["documents"] == []
    assert result["messages"][-1].content == "clarifying reply"
    assert model.structured_calls == ["Router"]  # never planned


async def test_plan_is_truncated_to_the_configured_budget(stub_agent):
    stub_agent(steps=("one", "two", "three", "four", "five"))

    result = await research_graph.ainvoke(
        {"messages": [{"role": "user", "content": "big question"}]},
        {"configurable": {"max_research_steps": 2}},
    )

    assert result["messages"][-1].content == "final answer"
    assert result["steps"] == ["one", "two"]
    assert len(result["completed_steps"]) == 2  # no task ran for a truncated step


async def test_empty_plan_falls_back_to_researching_the_question(stub_agent):
    # A planner returning nothing must not lead to an answer with no evidence.
    stub_agent(steps=())

    result = await research_graph.ainvoke(
        {"messages": [{"role": "user", "content": "why overlap chunks?"}]}
    )

    assert result["documents"], "should have researched the question as asked"


async def test_plan_steps_are_researched_concurrently(stub_agent):
    # Each task blocks until all have started: deadlocks if run sequentially.
    stub_agent(steps=("a", "b", "c"))

    class _BlockingRetriever:
        def __init__(self, expected):
            self.expected = expected
            self.started = 0
            self.all_started = asyncio.Event()

        async def ainvoke(self, query, config=None):
            self.started += 1
            if self.started >= self.expected:
                self.all_started.set()
            await asyncio.wait_for(self.all_started.wait(), timeout=5)
            return CORPUS

    retriever = _BlockingRetriever(expected=3)

    @contextmanager
    def fake_make_retriever(config):
        yield retriever

    with patch.object(retrieval_module, "make_retriever", fake_make_retriever):
        result = await research_graph.ainvoke(
            {"messages": [{"role": "user", "content": "why overlap chunks?"}]}
        )

    assert len(result["completed_steps"]) == 3


async def test_insufficient_evidence_abstains_instead_of_answering(stub_agent):
    model = stub_agent(sufficient=False, text="I could not find that in the corpus.")

    result = await research_graph.ainvoke(
        {"messages": [{"role": "user", "content": "what does Kafka guarantee?"}]}
    )

    assert result["evidence"]["sufficient"] is False
    assert result["evidence"]["missing"] == "a paper about overlap"
    assert result["citations"] == []  # an abstention cites nothing
    assert "EvidenceAssessment" in model.structured_calls
    assert result["messages"][-1].content == "I could not find that in the corpus."


async def test_retrieving_nothing_abstains_without_asking_the_model(stub_agent):
    model = stub_agent(corpus=[])

    result = await research_graph.ainvoke(
        {"messages": [{"role": "user", "content": "what does Kafka guarantee?"}]}
    )

    assert result["documents"] == []
    assert result["evidence"]["sufficient"] is False
    # No evidence is a fact about state, not a judgement call for an LLM.
    assert "EvidenceAssessment" not in model.structured_calls


async def test_citations_resolve_to_the_documents_that_were_retrieved(stub_agent):
    stub_agent(text="Overlap keeps sentences whole [1]. Fusion merges lists [2].")

    result = await research_graph.ainvoke(
        {"messages": [{"role": "user", "content": "why overlap chunks?"}]}
    )

    assert [c["number"] for c in result["citations"]] == [1, 2]
    assert {c["title"] for c in result["citations"]} == {"Chunking", "Fusion"}
    assert all(c["resolved"] for c in result["citations"])


async def test_a_citation_beyond_the_evidence_is_flagged_unresolved(stub_agent):
    stub_agent(text="A claim with an invented reference [9].")

    result = await research_graph.ainvoke(
        {"messages": [{"role": "user", "content": "why overlap chunks?"}]}
    )

    assert [(c["number"], c["resolved"]) for c in result["citations"]] == [(9, False)]


async def test_structured_calls_ask_for_json_schema_decoding(stub_agent):
    # Groq's gpt-oss models decline the forced tool call function_calling needs.
    model = stub_agent(steps=("a",))

    await research_graph.ainvoke(
        {"messages": [{"role": "user", "content": "why overlap chunks?"}]}
    )

    assert model.structured_calls  # it really did bind schemas
    assert set(model.methods) == {"json_schema"}
