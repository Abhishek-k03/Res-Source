"""Collections: create, list, and delete an isolated corpus."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api import services
from api.db import commit_now, get_session
from api.models import Collection, Source
from api.schemas import CollectionCreate, CollectionOut

router = APIRouter(prefix="/collections", tags=["collections"])


async def load_collection(collection_id: str, session: AsyncSession) -> Collection:
    """Fetch a collection by id or slug, or 404."""
    collection = await session.get(Collection, collection_id)
    if collection is None:
        collection = await session.scalar(
            select(Collection).where(Collection.slug == collection_id)
        )
    if collection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collection not found")
    return collection


@router.post("", response_model=CollectionOut, status_code=status.HTTP_201_CREATED)
async def create_collection(
    body: CollectionCreate, session: AsyncSession = Depends(get_session)
) -> CollectionOut:
    """Create a collection."""
    collection = Collection(
        slug=body.slug,
        name=body.name or body.slug,
        description=body.description,
        research_domain=body.research_domain,
        index_name=body.index_name,
        embedding_model=body.embedding_model,
    )
    session.add(collection)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Collection {body.slug!r} already exists"
        ) from exc
    await commit_now(session)
    return CollectionOut.model_validate(collection)


@router.get("", response_model=list[CollectionOut])
async def list_collections(
    session: AsyncSession = Depends(get_session),
) -> list[CollectionOut]:
    """List collections, newest first, with how many sources each holds."""
    counts: dict[str, int] = dict(
        (
            await session.execute(
                select(Source.collection_id, func.count(Source.id)).group_by(
                    Source.collection_id
                )
            )
        ).all()  # type: ignore[arg-type]
    )
    rows = await session.scalars(
        select(Collection).order_by(Collection.created_at.desc())
    )
    out = []
    for collection in rows:
        item = CollectionOut.model_validate(collection)
        item.source_count = int(counts.get(collection.id, 0))
        out.append(item)
    return out


@router.get("/{collection_id}", response_model=CollectionOut)
async def get_collection(
    collection_id: str, session: AsyncSession = Depends(get_session)
) -> CollectionOut:
    """Fetch one collection by id or slug."""
    collection = await load_collection(collection_id, session)
    item = CollectionOut.model_validate(collection)
    item.source_count = int(
        await session.scalar(
            select(func.count(Source.id)).where(Source.collection_id == collection.id)
        )
        or 0
    )
    return item


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    """Delete a collection, its rows, and its vectors."""
    collection = await load_collection(collection_id, session)
    await services.delete_collection_chunks(collection)
    await session.delete(collection)
    await commit_now(session)
