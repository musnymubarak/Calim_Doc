"""Ask a question against a document → runs the selective-spend answer pipeline."""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.services.answer_router import answer_question

router = APIRouter(prefix="/conversations", tags=["chat"])


class AskBody(BaseModel):
    question: str
    # Model-tier *preference* (not a safety override): invalid values are rejected with 422.
    # Hard verification/answerability/retrieval gates still force escalation regardless.
    tier: Literal["fast", "balanced", "accurate"] | None = None


@router.post("/{conversation_id}/messages")
async def ask(
    conversation_id: uuid.UUID,
    body: AskBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    convo = await db.get(Conversation, conversation_id)
    if convo is None or convo.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Persist the user's message.
    db.add(Message(conversation_id=conversation_id, role="user", content=body.question))
    await db.commit()

    # Run the escalation ladder (cache -> retrieve -> generate -> gates -> escalate).
    try:
        result = await answer_question(
            db=db,
            document_id=convo.document_id,
            question=body.question,
            tier_override=body.tier,
        )
    except Exception as e:
        error_str = str(e)
        if "429 RESOURCE_EXHAUSTED" in error_str:
            raise HTTPException(status_code=429, detail="API rate limit exceeded. Please wait a minute and try again.")
        if "503" in error_str or "UNAVAILABLE" in error_str:
            raise HTTPException(status_code=503, detail="The AI model is temporarily busy (high demand). Please try again in a moment.")
        raise HTTPException(status_code=500, detail=f"Failed to generate answer: {error_str}")

    msg = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=result.answer,
        citations=result.citations,
        exceptions=result.exceptions,
        answerable=result.answerable,
        missing_context=result.missing_context,
        confidence=result.confidence,
        model=result.model,
        tier=result.tier,
        escalated=result.escalated,
        escalation_reason=result.escalation_reason,
        token_usage=result.token_usage,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    return {
        "id": str(msg.id),
        "answer": result.answer,
        "citations": result.citations,
        "answerable": result.answerable,
        "confidence": result.confidence,
        "escalated": result.escalated,
        "token_usage": result.token_usage,
    }
