"""Resolve [n] citation markers in an answer back to the retrieved documents.

Citation numbers are model-generated, so a marker is a claim until it is mapped
onto real metadata; out-of-range ones are reported rather than dropped.
"""

from __future__ import annotations

import re
from typing import TypedDict

from langchain_core.documents import Document

# Some models emit CJK lenticular brackets for citations instead of ASCII ones.
_MARKER = re.compile(r"[\[【](\d{1,3})[\]】]")

_TITLE_KEYS = ("title", "source", "url")

SNIPPET_CHARS = 180
"""How much of a cited passage to carry back for display."""


class Citation(TypedDict):
    """One [n] marker, resolved against the retrieved documents."""

    number: int
    title: str
    source: str
    url: str
    snippet: str
    """Opening of the cited passage, so a reader can see the grounding."""
    resolved: bool
    """False when the number matches no retrieved document."""


def _label(metadata: dict) -> str:
    """Pick the most readable label the loader captured."""
    for key in _TITLE_KEYS:
        value = metadata.get(key)
        if value:
            return str(value)
    return "Untitled"


def _snippet(text: str) -> str:
    """Collapse a passage to one readable line.

    Leading Markdown heading markers are dropped: a chunk often starts mid-file
    on a heading, and "## Safety Raft never..." reads as noise.
    """
    flat = " ".join((text or "").split())
    flat = re.sub(r"^#{1,6}\s*", "", flat)
    if len(flat) <= SNIPPET_CHARS:
        return flat
    cut = flat[:SNIPPET_CHARS].rsplit(" ", 1)[0]
    return f"{cut}…"


def normalize_markers(answer: str) -> str:
    """Rewrite non-ASCII citation brackets so every provider reads the same."""
    return _MARKER.sub(lambda m: f"[{m.group(1)}]", answer)


def cited_numbers(answer: str) -> list[int]:
    """Return the distinct [n] markers in an answer, in ascending order."""
    return sorted({int(match) for match in _MARKER.findall(answer)})


def extract_citations(answer: str, docs: list[Document] | None) -> list[Citation]:
    """Resolve every [n] against the documents, numbered as format_docs rendered them."""
    documents = docs or []
    citations: list[Citation] = []
    for number in cited_numbers(answer):
        if 1 <= number <= len(documents):
            document = documents[number - 1]
            metadata = document.metadata or {}
            citations.append(
                Citation(
                    number=number,
                    title=_label(metadata),
                    source=str(metadata.get("source", "")),
                    url=str(metadata.get("url", "")),
                    snippet=_snippet(document.page_content),
                    resolved=True,
                )
            )
        else:
            citations.append(
                Citation(
                    number=number,
                    title="Unknown source",
                    source="",
                    url="",
                    snippet="",
                    resolved=False,
                )
            )
    return citations
