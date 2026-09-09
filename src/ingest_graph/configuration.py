"""Configurable parameters for the ingest graph."""

from __future__ import annotations

from dataclasses import dataclass, field

from shared.configuration import BaseConfiguration


@dataclass(kw_only=True)
class IngestConfiguration(BaseConfiguration):
    """How documents are fetched and chunked. What to ingest lives on IngestState."""

    docs_dir: str = field(
        default="data",
        metadata={"description": "Directory scanned when the source is 'files'."},
    )

    arxiv_max_results: int = field(
        default=5,
        metadata={"description": "How many papers to pull for an arXiv query."},
    )

    arxiv_full_text: bool = field(
        default=True,
        metadata={
            "description": "Parse each paper's PDF. False indexes abstracts only."
        },
    )

    chunk_size: int = field(
        default=1000,
        metadata={"description": "Target characters per chunk."},
    )

    chunk_overlap: int = field(
        default=200,
        metadata={"description": "Characters shared between neighbouring chunks."},
    )
