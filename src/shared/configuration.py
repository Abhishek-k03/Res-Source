"""Configuration shared by the ingest graph and the retrieval graph."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from typing import Annotated, Any, Literal, Type, TypeVar

from langchain_core.runnables import RunnableConfig, ensure_config


def _runtime_context() -> dict[str, Any]:
    """Read the LangGraph runtime context, or {} outside a graph run."""
    try:
        from langgraph.runtime import get_runtime

        context = get_runtime().context
    except (ImportError, RuntimeError, LookupError):
        return {}

    if context is None:
        return {}
    if isinstance(context, dict):
        return dict(context)
    if is_dataclass(context) and not isinstance(context, type):
        return {f.name: getattr(context, f.name) for f in fields(context)}
    return {}


@dataclass(kw_only=True)
class BaseConfiguration:
    """Settings both indexing and retrieval need, so the two cannot drift apart."""

    embedding_model: Annotated[
        str,
        {"__template_metadata__": {"kind": "embeddings"}},
    ] = field(
        default="fastembed/BAAI/bge-small-en-v1.5",
        metadata={
            "description": (
                "Embedding model as 'provider/model'. Providers: fastembed (local, no "
                "API key), google, huggingface (local), openai, cohere. Changing this "
                "changes the vector dimensions, so re-index into a fresh index_name."
            )
        },
    )

    retriever_provider: Annotated[
        Literal["elastic-local", "elastic", "pinecone", "mongodb"],
        {"__template_metadata__": {"kind": "retriever"}},
    ] = field(
        default="elastic-local",
        metadata={
            "description": (
                "Vector store backing retrieval. 'elastic-local' targets the "
                "docker-compose Elasticsearch; 'elastic' targets Elastic Cloud."
            )
        },
    )

    index_name: str = field(
        default="research_agent",
        metadata={"description": "Name of the vector index. One per corpus."},
    )

    collection_id: str | None = field(
        default=None,
        metadata={
            "description": (
                "Restrict indexing and retrieval to one collection inside the index. "
                "Collections share an index and are separated by a metadata filter, so "
                "they also share an embedding model. None means the whole index."
            )
        },
    )

    search_kwargs: dict[str, Any] = field(
        default_factory=lambda: {"k": 5},
        metadata={
            "description": "Arguments for the retriever's search call, e.g. {'k': 5}."
        },
    )

    @classmethod
    def from_runnable_config(cls: Type[T], config: RunnableConfig | None = None) -> T:
        """Build a configuration from config['configurable'], then runtime context.

        Unknown keys are ignored, so one config dict can be passed to graphs
        with different configuration classes.
        """
        config = ensure_config(config)
        values: dict[str, Any] = dict(config.get("configurable") or {})
        values.update(_runtime_context())
        _fields = {f.name for f in fields(cls) if f.init}
        return cls(**{k: v for k, v in values.items() if k in _fields})


T = TypeVar("T", bound=BaseConfiguration)
