"""Sources: add, upload, list, re-index, and delete. Ingestion never blocks the request."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import services
from api.db import commit_now, get_session
from api.models import IngestionJob, Source, SourceKind
from api.routers.collections import load_collection
from api.schemas import JobOut, SourceAccepted, SourceCreate, SourceOut
from api.settings import get_settings
from ingest_graph.loaders import SUPPORTED_SUFFIXES

router = APIRouter(tags=["sources"])

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(filename: str) -> str:
    """Reduce an uploaded filename to something safe to join onto a path."""
    cleaned = _UNSAFE.sub("_", Path(filename or "upload").name).strip("._-")
    return cleaned or "upload"


async def _existing(
    session: AsyncSession, collection_id: str, kind: SourceKind, locator: str
) -> Source | None:
    return await session.scalar(
        select(Source).where(
            Source.collection_id == collection_id,
            Source.kind == kind,
            Source.locator == locator,
        )
    )


@router.post(
    "/collections/{collection_id}/sources",
    response_model=SourceAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def add_source(
    collection_id: str,
    body: SourceCreate,
    session: AsyncSession = Depends(get_session),
) -> SourceAccepted:
    """Register an arXiv query or URL and queue it for ingestion."""
    collection = await load_collection(collection_id, session)
    source = await _existing(session, collection.id, body.kind, body.locator)
    if source is None:
        source = Source(
            collection_id=collection.id,
            kind=body.kind,
            locator=body.locator,
            title=body.title or body.locator,
        )
        session.add(source)
        await session.flush()

    job = await services.create_job(session, source)
    return SourceAccepted(
        source=SourceOut.model_validate(source), job=JobOut.model_validate(job)
    )


@router.post(
    "/collections/{collection_id}/sources/upload",
    response_model=SourceAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_source(
    collection_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> SourceAccepted:
    """Store an uploaded document and queue it for ingestion."""
    collection = await load_collection(collection_id, session)
    name = _safe_name(file.filename or "")
    if Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type. Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}",
        )

    # One directory per source: the ingest graph scans a directory, and this
    # keeps re-ingestion of one file from picking up its neighbours.
    root = Path(get_settings().upload_dir) / collection.slug / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    destination = root / name
    destination.write_bytes(await file.read())

    locator = str(root)
    source = await _existing(session, collection.id, SourceKind.files, locator)
    if source is None:
        source = Source(
            collection_id=collection.id,
            kind=SourceKind.files,
            locator=locator,
            title=name,
        )
        session.add(source)
        await session.flush()

    job = await services.create_job(session, source)
    return SourceAccepted(
        source=SourceOut.model_validate(source), job=JobOut.model_validate(job)
    )


async def _with_latest_jobs(
    session: AsyncSession, sources: list[Source]
) -> list[SourceOut]:
    """Attach each source's most recent job in one query, not one per source."""
    out = [SourceOut.model_validate(source) for source in sources]
    if not out:
        return out

    rows = await session.scalars(
        select(IngestionJob)
        .where(IngestionJob.source_id.in_([s.id for s in sources]))
        .order_by(IngestionJob.created_at.desc())
    )
    latest: dict[str, IngestionJob] = {}
    for job in rows:
        latest.setdefault(job.source_id, job)

    for item in out:
        newest = latest.get(item.id)
        if newest is not None:
            item.latest_job = JobOut.model_validate(newest)
    return out


@router.get("/collections/{collection_id}/sources", response_model=list[SourceOut])
async def list_sources(
    collection_id: str, session: AsyncSession = Depends(get_session)
) -> list[SourceOut]:
    """List a collection's sources, each with its latest ingestion job."""
    collection = await load_collection(collection_id, session)
    rows = await session.scalars(
        select(Source)
        .where(Source.collection_id == collection.id)
        .order_by(Source.created_at.desc())
    )
    return await _with_latest_jobs(session, list(rows))


@router.get("/sources/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: str, session: AsyncSession = Depends(get_session)
) -> SourceOut:
    """Fetch one source with its latest ingestion job."""
    source = await _load_source(session, source_id)
    return (await _with_latest_jobs(session, [source]))[0]


async def _load_source(session: AsyncSession, source_id: str) -> Source:
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    return source


@router.post(
    "/sources/{source_id}/reindex",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_source(
    source_id: str, session: AsyncSession = Depends(get_session)
) -> JobOut:
    """Re-ingest a source. Unchanged chunks update in place; edited ones are pruned."""
    source = await _load_source(session, source_id)
    job = await services.create_job(session, source)
    await commit_now(session)
    return JobOut.model_validate(job)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    """Delete a source, every chunk it put in the index, and any uploaded files."""
    source = await _load_source(session, source_id)
    collection = await load_collection(source.collection_id, session)
    await services.delete_source_chunks(collection, source)
    services.delete_uploaded_files(source)
    await session.delete(source)
    await commit_now(session)


@router.get("/sources/{source_id}/jobs", response_model=list[JobOut])
async def list_source_jobs(
    source_id: str, session: AsyncSession = Depends(get_session)
) -> list[JobOut]:
    """Ingestion history for one source."""
    await _load_source(session, source_id)
    rows = await session.scalars(
        select(IngestionJob)
        .where(IngestionJob.source_id == source_id)
        .order_by(IngestionJob.created_at.desc())
    )
    return [JobOut.model_validate(row) for row in rows]


@router.get("/jobs/{job_id}", response_model=JobOut, tags=["jobs"])
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> JobOut:
    """Poll one ingestion job."""
    job = await session.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return JobOut.model_validate(job)
