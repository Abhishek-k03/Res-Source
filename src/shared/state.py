"""Reducers shared across graph states."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Literal, Union

from langchain_core.documents import Document

UUID_KEY = "uuid"


def _generate_uuid(page_content: str) -> str:
    """Derive a stable UUID from a document's content."""
    md5_hash = hashlib.md5(page_content.encode()).hexdigest()
    return str(uuid.UUID(md5_hash))


def drop_dedup_key(docs: list[Document]) -> list[Document]:
    """Return copies of the documents without the internal de-duplication key.

    A text splitter copies a parent's metadata onto every chunk, so a persisted
    key would be shared by all chunks of one document and collapse an entire
    retrieval into one. Strip it on the way into and out of the vector store.
    """
    cleaned: list[Document] = []
    for doc in docs:
        if UUID_KEY not in (doc.metadata or {}):
            cleaned.append(doc)
            continue
        copy = doc.model_copy(deep=True)
        copy.metadata.pop(UUID_KEY, None)
        cleaned.append(copy)
    return cleaned


def reduce_docs(
    existing: list[Document] | None,
    new: Union[
        list[Document],
        list[dict[str, Any]],
        list[str],
        str,
        Literal["delete"],
    ],
) -> list[Document]:
    """Merge documents into state, dropping ones whose content is already there.

    Accepts Documents, dicts, or strings, or the literal "delete" to clear.
    """
    if new == "delete":
        return []

    existing_list = list(existing) if existing else []
    if isinstance(new, str):
        return existing_list + [
            Document(page_content=new, metadata={UUID_KEY: _generate_uuid(new)})
        ]

    new_list: list[Document] = []
    if isinstance(new, list):
        existing_ids = {doc.metadata.get(UUID_KEY) for doc in existing_list}
        for item in new:
            if isinstance(item, str):
                item_id = _generate_uuid(item)
                if item_id not in existing_ids:
                    new_list.append(
                        Document(page_content=item, metadata={UUID_KEY: item_id})
                    )
                    existing_ids.add(item_id)

            elif isinstance(item, dict):
                metadata = item.get("metadata", {})
                item_id = metadata.get(UUID_KEY) or _generate_uuid(
                    item.get("page_content", "")
                )
                if item_id not in existing_ids:
                    new_list.append(
                        Document(
                            **{**item, "metadata": {**metadata, UUID_KEY: item_id}}
                        )
                    )
                    existing_ids.add(item_id)

            elif isinstance(item, Document):
                item_id = item.metadata.get(UUID_KEY, "")
                if not item_id:
                    item_id = _generate_uuid(item.page_content)
                    new_item = item.model_copy(deep=True)
                    new_item.metadata[UUID_KEY] = item_id
                else:
                    new_item = item

                if item_id not in existing_ids:
                    new_list.append(new_item)
                    existing_ids.add(item_id)

    return existing_list + new_list
