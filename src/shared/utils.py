"""Helpers for loading chat models and rendering retrieved documents."""

from __future__ import annotations

import os
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable

_CITED_METADATA_KEYS = ("title", "source", "url", "authors", "published", "page")

DEFAULT_TIMEOUT = float(os.environ.get("LLM_TIMEOUT_SECONDS", "120"))
DEFAULT_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "2"))
STRUCTURED_ATTEMPTS = int(os.environ.get("LLM_STRUCTURED_ATTEMPTS", "3"))


def message_text(message: BaseMessage) -> str:
    """Extract the plain text of a message, whose content may be blocks."""
    content = message.content
    if isinstance(content, str):
        return content

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


def _format_doc(doc: Document, index: int) -> str:
    """Render one document as a numbered XML block."""
    metadata = doc.metadata or {}
    attrs = [f'index="{index}"']
    for key in _CITED_METADATA_KEYS:
        value = metadata.get(key)
        if value not in (None, "", []):
            attrs.append(f"{key}={str(value)!r}")
    return f"<document {' '.join(attrs)}>\n{doc.page_content}\n</document>"


def format_docs(docs: list[Document] | None) -> str:
    """Render documents as numbered XML so the model can cite them as [n]."""
    if not docs:
        return "<documents></documents>"
    formatted = "\n".join(_format_doc(doc, i) for i, doc in enumerate(docs, start=1))
    return f"<documents>\n{formatted}\n</documents>"


def structured_output(model: BaseChatModel, schema: type) -> Runnable:
    """Bind a schema so the model reliably returns it.

    Two provider quirks are handled here. Groq's gpt-oss models routinely
    decline the forced tool call that the default `function_calling` method
    depends on, so JSON-schema decoding is preferred where it exists. Those
    models also return an empty generation for roughly one structured call in
    ten, which arrives as a non-retryable 400; a graph making four such calls
    per question needs them retried, not propagated.
    """
    try:
        bound = model.with_structured_output(schema, method="json_schema")
    except (TypeError, ValueError, NotImplementedError):
        bound = model.with_structured_output(schema)

    with_retry = getattr(bound, "with_retry", None)
    if with_retry is None:
        return bound
    return with_retry(
        stop_after_attempt=STRUCTURED_ATTEMPTS, wait_exponential_jitter=True
    )


def load_chat_model(
    fully_specified_name: str,
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
) -> BaseChatModel:
    """Load a chat model from a 'provider/model' string.

    A bounded timeout and retry count matter here: a quota-throttled model
    otherwise retries with backoff indefinitely, which surfaces as a request
    that hangs rather than one that fails.
    """
    if "/" in fully_specified_name:
        provider, model = fully_specified_name.split("/", maxsplit=1)
    else:
        provider = ""
        model = fully_specified_name

    limits: dict[str, Any] = {
        "timeout": DEFAULT_TIMEOUT if timeout is None else timeout,
        "max_retries": DEFAULT_MAX_RETRIES if max_retries is None else max_retries,
    }
    try:
        return init_chat_model(model, model_provider=provider, **limits)
    except TypeError:
        # A provider that does not accept these kwargs.
        return init_chat_model(model, model_provider=provider)
