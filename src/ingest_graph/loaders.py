"""Document loaders for the ingest graph.

Each loader returns Documents with the same metadata keys -- source, title, and
where available url, authors, published -- so the rest of the pipeline does not
care where a document came from. Individual failures are logged and skipped.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = frozenset({".pdf", ".txt", ".md", ".markdown", ".html", ".htm"})


def _load_single_file(path: Path) -> list[Document]:
    """Load one file, dispatching on its extension."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from langchain_community.document_loaders import PyPDFLoader

        return PyPDFLoader(str(path)).load()
    if suffix in {".html", ".htm"}:
        from langchain_community.document_loaders import BSHTMLLoader

        return BSHTMLLoader(str(path), open_encoding="utf-8").load()

    text = path.read_text(encoding="utf-8", errors="replace")
    return [Document(page_content=text)]


def load_local_files(
    docs_dir: str, suffixes: Iterable[str] | None = None
) -> list[Document]:
    """Load every supported file under a directory, recursively."""
    root = Path(docs_dir)
    if not root.exists():
        logger.warning("Documents directory %s does not exist; nothing to load.", root)
        return []

    accepted = frozenset(s.lower() for s in (suffixes or SUPPORTED_SUFFIXES))
    documents: list[Document] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if path.suffix.lower() not in accepted:
            continue
        try:
            loaded = _load_single_file(path)
        except Exception:
            logger.exception("Failed to load %s; skipping.", path)
            continue

        for doc in loaded:
            doc.metadata = {**doc.metadata, "source": str(path), "title": path.name}
        documents.extend(loaded)

    logger.info("Loaded %d document(s) from %s", len(documents), root)
    return documents


def _fetch_pdf_text(pdf_url: str) -> str:
    """Download a PDF and extract its text, or return "" if that fails."""
    try:
        import pymupdf
        import requests

        response = requests.get(pdf_url, timeout=60)
        response.raise_for_status()
        with pymupdf.open(stream=response.content, filetype="pdf") as pdf:
            return "\n".join(page.get_text() for page in pdf)
    except Exception:
        logger.warning("Could not read PDF %s; falling back to the abstract.", pdf_url)
        return ""


def load_arxiv(
    query: str, max_results: int = 5, full_text: bool = True
) -> list[Document]:
    """Search arXiv and load the matching papers.

    Uses the arxiv client directly; the langchain-community wrapper still calls
    Search.results(), removed in arxiv 2.0. Papers whose PDF cannot be read fall
    back to their abstract.
    """
    if not query.strip():
        logger.warning("Empty arXiv query; nothing to load.")
        return []

    import arxiv

    try:
        client = arxiv.Client(num_retries=3, delay_seconds=3.0)
        search = arxiv.Search(query=query, max_results=max_results)
        results = list(client.results(search))
    except Exception:
        logger.exception("arXiv search for %r failed.", query)
        return []

    documents: list[Document] = []
    for result in results:
        content = _fetch_pdf_text(result.pdf_url) if full_text else ""
        documents.append(
            Document(
                page_content=content or result.summary,
                metadata={
                    "source": result.entry_id,
                    "title": result.title,
                    "url": result.entry_id,
                    "authors": ", ".join(a.name for a in result.authors),
                    "published": result.published.date().isoformat(),
                },
            )
        )

    logger.info("Loaded %d arXiv paper(s) for query %r", len(documents), query)
    return documents


def load_urls(urls: list[str]) -> list[Document]:
    """Fetch and extract the readable text of web pages."""
    if not urls:
        logger.warning("No URLs supplied; nothing to load.")
        return []

    from langchain_community.document_loaders import WebBaseLoader

    documents: list[Document] = []
    for url in urls:
        try:
            loaded = WebBaseLoader(url).load()
        except Exception:
            logger.exception("Failed to fetch %s; skipping.", url)
            continue

        for doc in loaded:
            doc.metadata = {
                **doc.metadata,
                "source": url,
                "url": url,
                "title": doc.metadata.get("title") or url,
            }
        documents.extend(loaded)

    logger.info("Loaded %d document(s) from %d URL(s)", len(documents), len(urls))
    return documents
