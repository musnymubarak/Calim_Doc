"""List documents and poll ingestion status."""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.document import Document
from app.models.user import User

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("")
async def list_documents(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Document)
        .options(selectinload(Document.risk_report))
        .where(Document.user_id == user.id)
        .order_by(Document.created_at.desc())
    )
    return [
        {
            "id": str(d.id),
            "filename": d.filename,
            "page_count": d.page_count,
            "status": d.status,
            "mime_type": d.mime_type,
            "report_status": d.risk_report.status if d.risk_report else None,
            "strategy": d.strategy,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in result.scalars()
    ]


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Document)
        .options(selectinload(Document.risk_report))
        .where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "page_count": doc.page_count,
        "status": doc.status,
        "mime_type": doc.mime_type,
        "report_status": doc.risk_report.status if doc.risk_report else None,
        "error_msg": doc.error_msg,
        "strategy": doc.strategy,
    }


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """Serve the raw uploaded file (for in-app preview). Owner-scoped."""
    doc = await db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.storage_uri or not os.path.isfile(doc.storage_uri):
        raise HTTPException(status_code=404, detail="File is no longer available")
    return FileResponse(
        doc.storage_uri,
        media_type=doc.mime_type or "application/octet-stream",
        filename=doc.filename,
        content_disposition_type="inline",  # preview in-browser instead of downloading
    )
