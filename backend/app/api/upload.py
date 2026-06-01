"""Upload endpoint: store raw file, content-hash dedup, enqueue ingestion."""
from __future__ import annotations

import hashlib

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_arq_pool, get_current_user
from app.db.session import get_db
from app.models.document import Document
from app.models.user import User
from app.services.storage import get_storage

router = APIRouter(prefix="/documents", tags=["upload"])


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    arq: ArqRedis = Depends(get_arq_pool),
) -> dict:
    data = await file.read()
    content_hash = hashlib.sha256(data).hexdigest()

    # Content-hash dedup: same user + same bytes → reuse, skip re-ingest.
    existing = await db.execute(
        select(Document).where(
            Document.user_id == user.id, Document.content_hash == content_hash
        )
    )
    dup = existing.scalar_one_or_none()
    if dup is not None:
        return {"document_id": str(dup.id), "status": dup.status, "deduped": True}

    storage = get_storage()
    storage_uri = storage.save(user_id=str(user.id), content_hash=content_hash,
                               filename=file.filename or "upload", data=data)

    doc = Document(
        user_id=user.id,
        filename=file.filename or "upload",
        mime_type=file.content_type or "application/octet-stream",
        storage_uri=storage_uri,
        content_hash=content_hash,
        status="uploaded",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Hand off heavy work to the worker (parse/chunk/embed).
    await arq.enqueue_job("ingest_document", str(doc.id))

    return {"document_id": str(doc.id), "status": doc.status, "deduped": False}
