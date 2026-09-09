"""State for the researcher subgraph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from langchain_core.documents import Document

from shared.state import reduce_docs


@dataclass(kw_only=True)
class QueryState:
    """Private state for a single fanned-out retrieve_documents task."""

    query: str


@dataclass(kw_only=True)
class ResearcherState:
    """One research step and everything found for it."""

    question: str
    """A single self-contained step from the parent graph's research plan."""

    queries: list[str] = field(default_factory=list)
    """Search queries generated to cover the question from different angles."""

    documents: Annotated[list[Document], reduce_docs] = field(default_factory=list)
    """Retrieved chunks, merged across the parallel queries."""
