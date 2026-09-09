"""Embedding and vector store factories.

Backends are imported lazily, so only the provider you select needs installing.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Generator

from langchain_core.embeddings import Embeddings
from langchain_core.runnables import RunnableConfig
from langchain_core.vectorstores import VectorStoreRetriever

from shared.configuration import BaseConfiguration

COLLECTION_KEY = "collection_id"


def collection_filter(collection_id: str | None) -> list[dict[str, Any]]:
    """Build the Elasticsearch clauses restricting a search to one collection."""
    if not collection_id:
        return []
    # .keyword is the exact-match half of ES's default dynamic string mapping.
    return [{"term": {f"metadata.{COLLECTION_KEY}.keyword": collection_id}}]


def scoped_search_kwargs(configuration: BaseConfiguration) -> dict[str, Any]:
    """Add the collection filter to the configured search arguments."""
    kwargs = dict(configuration.search_kwargs)
    clauses = collection_filter(configuration.collection_id)
    if clauses:
        kwargs["filter"] = [*kwargs.get("filter", []), *clauses]
    return kwargs


def _reject_unscoped(configuration: BaseConfiguration) -> None:
    """Refuse to search rather than silently ignore the collection scope."""
    if configuration.collection_id:
        raise NotImplementedError(
            f"collection_id is not supported by retriever_provider "
            f"{configuration.retriever_provider!r}; collections are implemented for "
            f"Elasticsearch only."
        )


@lru_cache(maxsize=4)
def make_text_encoder(model: str) -> Embeddings:
    """Build the embeddings for a 'provider/model' string.

    Cached: a fastembed encoder loads an ONNX model per construction, and
    retrieval builds one per query.
    """
    provider, model = model.split("/", maxsplit=1)
    match provider:
        case "fastembed":
            from langchain_community.embeddings.fastembed import FastEmbedEmbeddings

            return FastEmbedEmbeddings(model_name=model)
        case "huggingface":
            from langchain_huggingface import HuggingFaceEmbeddings

            return HuggingFaceEmbeddings(model_name=model)
        case "google":
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            if not model.startswith("models/"):
                model = f"models/{model}"
            return GoogleGenerativeAIEmbeddings(model=model)
        case "openai":
            from langchain_openai import OpenAIEmbeddings

            return OpenAIEmbeddings(model=model)
        case "cohere":
            from langchain_cohere import CohereEmbeddings

            return CohereEmbeddings(model=model)  # type: ignore[call-arg]
        case _:
            raise ValueError(f"Unsupported embedding provider: {provider}")


@contextmanager
def make_elastic_retriever(
    configuration: BaseConfiguration, embedding_model: Embeddings
) -> Generator[VectorStoreRetriever, None, None]:
    """Connect to an Elasticsearch index, local or Elastic Cloud."""
    from langchain_elasticsearch import ElasticsearchStore

    if configuration.retriever_provider == "elastic-local":
        connection_options = {
            "es_user": os.environ.get("ELASTICSEARCH_USER", "elastic"),
            "es_password": os.environ.get("ELASTICSEARCH_PASSWORD", "changeme"),
        }
    else:
        connection_options = {"es_api_key": os.environ["ELASTICSEARCH_API_KEY"]}

    vstore = ElasticsearchStore(
        **connection_options,  # type: ignore[arg-type]
        es_url=os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200"),
        index_name=configuration.index_name,
        embedding=embedding_model,
    )
    yield vstore.as_retriever(search_kwargs=scoped_search_kwargs(configuration))


@contextmanager
def make_pinecone_retriever(
    configuration: BaseConfiguration, embedding_model: Embeddings
) -> Generator[VectorStoreRetriever, None, None]:
    """Connect to an existing Pinecone index."""
    from langchain_pinecone import PineconeVectorStore

    _reject_unscoped(configuration)
    vstore = PineconeVectorStore.from_existing_index(
        os.environ["PINECONE_INDEX_NAME"], embedding=embedding_model
    )
    yield vstore.as_retriever(search_kwargs=configuration.search_kwargs)


@contextmanager
def make_mongodb_retriever(
    configuration: BaseConfiguration, embedding_model: Embeddings
) -> Generator[VectorStoreRetriever, None, None]:
    """Connect to a MongoDB Atlas vector search index."""
    from langchain_mongodb.vectorstores import MongoDBAtlasVectorSearch

    _reject_unscoped(configuration)
    vstore = MongoDBAtlasVectorSearch.from_connection_string(
        os.environ["MONGODB_URI"],
        namespace=f"research_agent.{configuration.index_name}",
        embedding=embedding_model,
    )
    yield vstore.as_retriever(search_kwargs=configuration.search_kwargs)


@contextmanager
def make_retriever(
    config: RunnableConfig,
) -> Generator[VectorStoreRetriever, None, None]:
    """Create the retriever selected by the current configuration."""
    configuration = BaseConfiguration.from_runnable_config(config)
    embedding_model = make_text_encoder(configuration.embedding_model)
    match configuration.retriever_provider:
        case "elastic" | "elastic-local":
            with make_elastic_retriever(configuration, embedding_model) as retriever:
                yield retriever
        case "pinecone":
            with make_pinecone_retriever(configuration, embedding_model) as retriever:
                yield retriever
        case "mongodb":
            with make_mongodb_retriever(configuration, embedding_model) as retriever:
                yield retriever
        case _:
            raise ValueError(
                f"Unrecognized retriever_provider: {configuration.retriever_provider}"
            )
