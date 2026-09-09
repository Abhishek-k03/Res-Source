"""Researcher subgraph: turn one research step into retrieved documents.

generate_queries -> (fan out) retrieve_documents

Several differently-worded queries cover vocabulary the user did not use, which
single-query vector search misses.
"""

from __future__ import annotations

from typing import TypedDict, cast

from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from retrieval_graph.configuration import AgentConfiguration
from retrieval_graph.researcher_graph.state import QueryState, ResearcherState
from shared import retrieval
from shared.state import drop_dedup_key
from shared.utils import load_chat_model, structured_output


class SearchQueries(TypedDict):
    """Search queries covering one research step."""

    queries: list[str]


async def generate_queries(
    state: ResearcherState, *, config: RunnableConfig
) -> dict[str, list[str]]:
    """Expand the research step into several diverse search queries."""
    configuration = AgentConfiguration.from_runnable_config(config)
    model = structured_output(load_chat_model(configuration.query_model), SearchQueries)
    system_prompt = configuration.generate_queries_system_prompt.format(
        count=configuration.queries_per_step,
        domain=configuration.research_domain,
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "human", "content": state.question},
    ]
    response = cast(SearchQueries, await model.ainvoke(messages))
    return {"queries": response.get("queries") or [state.question]}


async def retrieve_documents(
    state: QueryState, *, config: RunnableConfig
) -> dict[str, list[Document]]:
    """Retrieve documents for a single query."""
    with retrieval.make_retriever(config) as retriever:
        response = await retriever.ainvoke(state.query, config)
    return {"documents": drop_dedup_key(response)}


def retrieve_in_parallel(state: ResearcherState) -> list[Send]:
    """Dispatch one retrieve_documents task per generated query."""
    return [
        Send("retrieve_documents", QueryState(query=query)) for query in state.queries
    ]


builder = StateGraph(ResearcherState, context_schema=AgentConfiguration)
builder.add_node(generate_queries)
builder.add_node(retrieve_documents)

builder.add_edge(START, "generate_queries")
builder.add_conditional_edges(
    "generate_queries",
    retrieve_in_parallel,  # type: ignore[arg-type]
    path_map=["retrieve_documents"],
)
builder.add_edge("retrieve_documents", END)

graph = builder.compile()
graph.name = "ResearcherGraph"
