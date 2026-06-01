"""List documents and poll ingestion status."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
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
    result = await db.execute(
        select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc())
    )
    return [
        {
            "id": str(d.id),
            "filename": d.filename,
            "page_count": d.page_count,
            "status": d.status,
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
    doc = await db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "page_count": doc.page_count,
        "status": doc.status,
        "error_msg": doc.error_msg,
        "strategy": doc.strategy,
    }
