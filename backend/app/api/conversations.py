"""Create and list conversations scoped to a document."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.user import User

router = APIRouter(prefix="/conversations", tags=["conversations"])


class CreateConversation(BaseModel):
    document_id: uuid.UUID


@router.post("")
async def create_conversation(
    body: CreateConversation,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    doc = await db.get(Document, body.document_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")

    convo = Conversation(document_id=body.document_id, user_id=user.id)
    db.add(convo)
    await db.commit()
    await db.refresh(convo)
    return {"id": str(convo.id), "document_id": str(convo.document_id)}


@router.get("")
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    result = await db.execute(
        select(Conversation).where(Conversation.user_id == user.id)
    )
    return [
        {"id": str(c.id), "document_id": str(c.document_id)} for c in result.scalars()
    ]
