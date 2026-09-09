"""State for the retrieval graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Literal, TypedDict, Union

from langchain_core.documents import Document
from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from shared.citations import Citation
from shared.state import reduce_docs


@dataclass(kw_only=True)
class InputState:
    """The agent's public interface: just the conversation."""

    messages: Annotated[list[AnyMessage], add_messages]
    """The conversation so far. Merged by id, so re-sending a message updates it."""


class Router(TypedDict):
    """The triage decision about a user's message."""

    logic: str
    """Why this classification was chosen. Passed on to the responding node."""
    type: Literal["more-info", "research", "general"]
    """Which branch should handle the message."""


class StepResult(TypedDict):
    """What one finished research task found."""

    step: str
    document_count: int


def merge_step_results(
    existing: list[StepResult] | None,
    new: Union[list[StepResult], Literal["delete"]],
) -> list[StepResult]:
    """Append finished research tasks, or clear them for a new question.

    Without the reset, a checkpointed thread carries the previous question's
    progress into the next one.
    """
    if new == "delete":
        return []
    return list(existing or []) + list(new)


@dataclass(kw_only=True)
class ResearchTask:
    """Private state for one fanned-out research task."""

    step: str


class EvidenceAssessment(TypedDict):
    """Whether the collected evidence can support an answer at all."""

    sufficient: bool
    reason: str
    missing: str
    """What the corpus would need to make the question answerable."""


@dataclass(kw_only=True)
class AgentState(InputState):
    """Full working state of the research agent."""

    router: Router = field(default_factory=lambda: Router(type="general", logic=""))
    """The router's classification of the latest user message."""

    steps: list[str] = field(default_factory=list)
    """The research plan. Retained once created, since the tasks run in parallel."""

    completed_steps: Annotated[list[StepResult], merge_step_results] = field(
        default_factory=list
    )
    """Finished research tasks, appended as each one lands."""

    documents: Annotated[list[Document], reduce_docs] = field(default_factory=list)
    """Everything retrieved for this question, de-duplicated."""

    evidence: EvidenceAssessment = field(
        default_factory=lambda: EvidenceAssessment(
            sufficient=True, reason="", missing=""
        )
    )
    """The sufficiency gate's verdict on the retrieved evidence."""

    citations: list[Citation] = field(default_factory=list)
    """The answer's [n] markers, resolved back to retrieved source metadata."""
