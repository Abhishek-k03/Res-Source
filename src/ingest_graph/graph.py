"""Ingest graph: load documents, chunk them, index them.

load_documents -> split_documents -> index_documents -> prune_stale_chunks
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from ingest_graph.configuration import IngestConfiguration
from ingest_graph.loaders import load_arxiv, load_local_files, load_urls
from ingest_graph.state import IngestState
from shared import retrieval
from shared.retrieval import COLLECTION_KEY, collection_filter
from shared.state import drop_dedup_key

logger = logging.getLogger(__name__)


def chunk_id(doc: Document) -> str:
    """Derive a stable id from a chunk's collection, source, and content.

    Re-ingesting the same content updates in place. An unscoped chunk hashes
    exactly as before, so existing indexes stay idempotent.
    """
    collection = str(doc.metadata.get(COLLECTION_KEY, "") or "")
    source = str(doc.metadata.get("source", ""))
    prefix = f"{collection}\x00" if collection else ""
    digest = hashlib.sha256(f"{prefix}{source}\x00{doc.page_content}".encode())
    return digest.hexdigest()


async def load_documents(
    state: IngestState, *, config: RunnableConfig
) -> dict[str, Any]:
    """Fetch documents from the chosen source, unless state already has some."""
    if state.docs:
        logger.info("Using %d document(s) supplied in state.", len(state.docs))
        return {}

    # The loaders block on network and PDF parsing. Off the event loop they go,
    # or one ingestion stalls every other job running concurrently.
    configuration = IngestConfiguration.from_runnable_config(config)
    match state.source:
        case "files":
            docs = await asyncio.to_thread(load_local_files, configuration.docs_dir)
        case "arxiv":
            docs = await asyncio.to_thread(
                load_arxiv,
                state.query,
                configuration.arxiv_max_results,
                configuration.arxiv_full_text,
            )
        case "urls":
            docs = await asyncio.to_thread(load_urls, state.urls)
        case _:
            raise ValueError(
                f"Unknown source {state.source!r}. Expected 'files', 'arxiv', or 'urls'."
            )

    return {"docs": docs}


async def split_documents(
    state: IngestState, *, config: RunnableConfig
) -> dict[str, Any]:
    """Split documents into overlapping chunks sized for embedding."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    configuration = IngestConfiguration.from_runnable_config(config)
    if not state.docs:
        return {"chunks": []}

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=configuration.chunk_size,
        chunk_overlap=configuration.chunk_overlap,
        add_start_index=True,
    )
    chunks = drop_dedup_key(
        await asyncio.to_thread(splitter.split_documents, state.docs)
    )
    if configuration.collection_id:
        for chunk in chunks:
            chunk.metadata[COLLECTION_KEY] = configuration.collection_id

    logger.info("Split %d document(s) into %d chunk(s).", len(state.docs), len(chunks))
    return {"chunks": chunks}


async def index_documents(
    state: IngestState, *, config: RunnableConfig
) -> dict[str, Any]:
    """Write the chunks to the vector store and clear them from state."""
    if not state.chunks:
        logger.warning("Nothing to index.")
        return {"indexed_count": 0, "docs": "delete", "chunks": []}

    by_id = {chunk_id(doc): doc for doc in state.chunks}
    sources = sorted(
        {
            str(doc.metadata.get("source", ""))
            for doc in state.chunks
            if doc.metadata.get("source")
        }
    )
    with retrieval.make_retriever(config) as retriever:
        await retriever.vectorstore.aadd_documents(
            list(by_id.values()), ids=list(by_id.keys())
        )

    logger.info("Indexed %d chunk(s).", len(by_id))
    return {
        "indexed_count": len(by_id),
        "indexed_ids": list(by_id.keys()),
        "indexed_sources": sources,
        "docs": "delete",
        "chunks": [],
    }


async def prune_stale_chunks(
    state: IngestState, *, config: RunnableConfig
) -> dict[str, Any]:
    """Delete chunks left behind by an earlier version of a re-ingested source.

    Ids hash content, so an edited document stops writing its old chunks rather
    than replacing them. Runs after indexing so nothing is briefly absent.
    """
    configuration = IngestConfiguration.from_runnable_config(config)
    if not state.indexed_ids or not state.indexed_sources:
        return {"pruned_count": 0}
    if configuration.retriever_provider not in ("elastic", "elastic-local"):
        logger.info("Pruning is implemented for Elasticsearch only; skipping.")
        return {"pruned_count": 0}

    query = {
        "bool": {
            "must": [{"terms": {"metadata.source.keyword": state.indexed_sources}}],
            "must_not": [{"ids": {"values": state.indexed_ids}}],
            "filter": collection_filter(configuration.collection_id),
        }
    }
    with retrieval.make_retriever(config) as retriever:
        client = retriever.vectorstore.client  # type: ignore[attr-defined]
        if not client.indices.exists(index=configuration.index_name):
            return {"pruned_count": 0}
        response = client.delete_by_query(
            index=configuration.index_name,
            query=query,
            refresh=True,
            conflicts="proceed",
        )

    pruned = int(response.get("deleted", 0))
    if pruned:
        logger.info("Pruned %d stale chunk(s) from re-ingested sources.", pruned)
    return {"pruned_count": pruned}


builder = StateGraph(IngestState, context_schema=IngestConfiguration)
builder.add_node(load_documents)
builder.add_node(split_documents)
builder.add_node(index_documents)
builder.add_node(prune_stale_chunks)

builder.add_edge(START, "load_documents")
builder.add_edge("load_documents", "split_documents")
builder.add_edge("split_documents", "index_documents")
builder.add_edge("index_documents", "prune_stale_chunks")
builder.add_edge("prune_stale_chunks", END)

graph = builder.compile()
graph.name = "IngestGraph"
