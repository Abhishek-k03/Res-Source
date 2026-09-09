"""State for the ingest graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Literal

from langchain_core.documents import Document

from shared.state import reduce_docs

Source = Literal["files", "arxiv", "urls"]


@dataclass(kw_only=True)
class IngestState:
    """Inputs and working state for one ingestion run."""

    source: Source = "files"
    """Which loader to use."""

    query: str = ""
    """Search query, used when source is 'arxiv'."""

    urls: list[str] = field(default_factory=list)
    """Pages to fetch, used when source is 'urls'."""

    docs: Annotated[list[Document], reduce_docs] = field(default_factory=list)
    """Loaded documents. Supply these directly to bypass the loaders."""

    chunks: list[Document] = field(default_factory=list)
    """Split documents, as they will be written to the vector store."""

    indexed_count: int = 0
    """How many chunks the run wrote. The graph's output."""

    indexed_ids: list[str] = field(default_factory=list)
    """Vector store ids written this run. Everything else for the same source is stale."""

    indexed_sources: list[str] = field(default_factory=list)
    """Distinct source identifiers touched this run, used to scope pruning."""

    pruned_count: int = 0
    """How many superseded chunks were deleted after indexing."""
