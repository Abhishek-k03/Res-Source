"""The research agent.

analyze_and_route_query ─┬─> ask_for_more_info ─────────────────────────> END
                         ├─> respond_to_general_query ──────────────────> END
                         └─> create_research_plan
                                    │
                              (fan out, one task per plan step)
                                    ↓
                             conduct_research ×N
                                    ↓
                             assess_evidence ─┬─> respond ──> END
                                              └─> abstain ──> END
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict, cast

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from retrieval_graph.configuration import AgentConfiguration
from retrieval_graph.researcher_graph.graph import graph as researcher_graph
from retrieval_graph.state import (
    AgentState,
    EvidenceAssessment,
    InputState,
    ResearchTask,
    Router,
    StepResult,
)
from shared.citations import extract_citations, normalize_markers
from shared.utils import (
    format_docs,
    load_chat_model,
    message_text,
    structured_output,
)


class Plan(TypedDict):
    """A short, ordered research plan."""

    steps: list[str]


def _latest_user_question(state: AgentState) -> str:
    """Return the text of the most recent human message."""
    for message in reversed(state.messages):
        if message.type == "human":
            return message_text(message)
    return ""


async def analyze_and_route_query(
    state: AgentState, *, config: RunnableConfig
) -> dict[str, Router]:
    """Classify the user's message to pick a branch."""
    configuration = AgentConfiguration.from_runnable_config(config)
    model = load_chat_model(configuration.query_model)
    system_prompt = configuration.router_system_prompt.format(
        domain=configuration.research_domain
    )
    messages = [{"role": "system", "content": system_prompt}] + state.messages
    response = cast(Router, await structured_output(model, Router).ainvoke(messages))
    return {"router": response}


def route_query(
    state: AgentState,
) -> Literal["create_research_plan", "ask_for_more_info", "respond_to_general_query"]:
    """Map the router's classification onto the next node."""
    _type = state.router["type"]
    if _type == "research":
        return "create_research_plan"
    elif _type == "more-info":
        return "ask_for_more_info"
    elif _type == "general":
        return "respond_to_general_query"
    else:
        raise ValueError(f"Unknown router type {_type}")


async def ask_for_more_info(
    state: AgentState, *, config: RunnableConfig
) -> dict[str, list[BaseMessage]]:
    """Ask the user for the detail that is blocking research."""
    configuration = AgentConfiguration.from_runnable_config(config)
    model = load_chat_model(configuration.query_model)
    system_prompt = configuration.more_info_system_prompt.format(
        domain=configuration.research_domain, logic=state.router["logic"]
    )
    messages = [{"role": "system", "content": system_prompt}] + state.messages
    response = await model.ainvoke(messages)
    return {"messages": [response]}


async def respond_to_general_query(
    state: AgentState, *, config: RunnableConfig
) -> dict[str, list[BaseMessage]]:
    """Answer a message that does not call for searching the corpus."""
    configuration = AgentConfiguration.from_runnable_config(config)
    model = load_chat_model(configuration.query_model)
    system_prompt = configuration.general_system_prompt.format(
        domain=configuration.research_domain, logic=state.router["logic"]
    )
    messages = [{"role": "system", "content": system_prompt}] + state.messages
    response = await model.ainvoke(messages)
    return {"messages": [response]}


async def create_research_plan(
    state: AgentState, *, config: RunnableConfig
) -> dict[str, Any]:
    """Break the question into self-contained research steps.

    Truncated to max_research_steps, since models overshoot the limit given in
    the prompt and each step is a full retrieval round.
    """
    configuration = AgentConfiguration.from_runnable_config(config)
    model = structured_output(load_chat_model(configuration.query_model), Plan)
    system_prompt = configuration.research_plan_system_prompt.format(
        domain=configuration.research_domain,
        max_steps=configuration.max_research_steps,
    )
    messages = [{"role": "system", "content": system_prompt}] + state.messages
    response = cast(Plan, await model.ainvoke(messages))

    steps = [step for step in (response.get("steps") or []) if step.strip()]
    if not steps:
        steps = [_latest_user_question(state)]
    return {
        "steps": steps[: configuration.max_research_steps],
        "documents": "delete",
        "completed_steps": "delete",
    }


def research_in_parallel(state: AgentState) -> list[Send]:
    """Dispatch every plan step at once. Steps are written to be independent."""
    return [Send("conduct_research", ResearchTask(step=step)) for step in state.steps]


async def conduct_research(
    state: ResearchTask, *, config: RunnableConfig
) -> dict[str, Any]:
    """Research one step of the plan via the researcher subgraph."""
    result = await researcher_graph.ainvoke({"question": state.step}, config)
    documents = result["documents"]
    return {
        "documents": documents,
        "completed_steps": [StepResult(step=state.step, document_count=len(documents))],
    }


async def assess_evidence(
    state: AgentState, *, config: RunnableConfig
) -> dict[str, EvidenceAssessment]:
    """Decide whether the retrieved evidence can support an answer at all.

    A gate before synthesis, so abstaining is a decision the graph makes and
    reports rather than one the answer prompt merely asks for.
    """
    if not state.documents:
        return {
            "evidence": EvidenceAssessment(
                sufficient=False,
                reason="No documents were retrieved for any step of the plan.",
                missing="Sources covering this question, added to the collection.",
            )
        }

    configuration = AgentConfiguration.from_runnable_config(config)
    model = structured_output(
        load_chat_model(configuration.query_model), EvidenceAssessment
    )
    system_prompt = configuration.evidence_assessment_system_prompt.format(
        domain=configuration.research_domain,
        context=format_docs(state.documents),
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "human", "content": _latest_user_question(state)},
    ]
    assessment = cast(EvidenceAssessment, await model.ainvoke(messages))
    return {
        "evidence": EvidenceAssessment(
            sufficient=bool(assessment.get("sufficient")),
            reason=str(assessment.get("reason", "")),
            missing=str(assessment.get("missing", "")),
        )
    }


def route_after_assessment(state: AgentState) -> Literal["respond", "abstain"]:
    """Answer only when the evidence was judged able to support one."""
    return "respond" if state.evidence["sufficient"] else "abstain"


async def abstain(state: AgentState, *, config: RunnableConfig) -> dict[str, Any]:
    """Say that the corpus cannot answer, and what would make it able to."""
    configuration = AgentConfiguration.from_runnable_config(config)
    model = load_chat_model(configuration.response_model)
    system_prompt = configuration.abstain_system_prompt.format(
        domain=configuration.research_domain,
        reason=state.evidence["reason"],
        missing=state.evidence["missing"],
    )
    messages = [{"role": "system", "content": system_prompt}] + state.messages
    response = await model.ainvoke(messages)
    return {"messages": [response], "citations": []}


async def respond(state: AgentState, *, config: RunnableConfig) -> dict[str, Any]:
    """Write the final answer, citing the retrieved documents."""
    configuration = AgentConfiguration.from_runnable_config(config)
    model = load_chat_model(configuration.response_model)
    system_prompt = configuration.response_system_prompt.format(
        domain=configuration.research_domain,
        context=format_docs(state.documents),
    )
    messages = [{"role": "system", "content": system_prompt}] + state.messages
    response = await model.ainvoke(messages)
    answer = normalize_markers(message_text(response))
    response.content = answer
    citations = extract_citations(answer, state.documents)
    return {"messages": [response], "citations": citations}


builder = StateGraph(
    AgentState, input_schema=InputState, context_schema=AgentConfiguration
)
builder.add_node(analyze_and_route_query)
builder.add_node(ask_for_more_info)
builder.add_node(respond_to_general_query)
builder.add_node(create_research_plan)
builder.add_node(conduct_research)
builder.add_node(assess_evidence)
builder.add_node(abstain)
builder.add_node(respond)

builder.add_edge(START, "analyze_and_route_query")
builder.add_conditional_edges("analyze_and_route_query", route_query)
builder.add_conditional_edges(
    "create_research_plan",
    research_in_parallel,  # type: ignore[arg-type]
    path_map=["conduct_research"],
)
# One edge, not a loop: every fanned-out task lands before assessment runs.
builder.add_edge("conduct_research", "assess_evidence")
builder.add_conditional_edges("assess_evidence", route_after_assessment)
builder.add_edge("ask_for_more_info", END)
builder.add_edge("respond_to_general_query", END)
builder.add_edge("abstain", END)
builder.add_edge("respond", END)

graph = builder.compile()
graph.name = "ResearchAgent"
