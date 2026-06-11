"""Route a question to the right answer engine based on the document's ingestion strategy.

- strategy == "rag": the doc was too large for whole-file Gemini attachment, so it was
  chunked + embedded → use the retrieval/escalation pipeline.
- otherwise ("files" / legacy): the whole doc is attached to Gemini directly.

Both engines expose the same answer_question(db, document_id, question, tier_override)
signature and return an AnswerResult with the fields chat.py consumes.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.services.answers.pipeline import answer_question as _answer_rag
from app.services.gemini_files.engine import answer_question as _answer_files


async def answer_question(
    db: AsyncSession,
    document_id: uuid.UUID,
    question: str,
    tier_override: str | None = None,
):
    doc = await db.get(Document, document_id)
    if doc is not None and doc.strategy == "rag":
        return await _answer_rag(db, document_id, question, tier_override=tier_override)
    return await _answer_files(db, document_id, question, tier_override=tier_override)
