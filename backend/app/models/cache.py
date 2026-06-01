"""Answer cache. NEVER cache unverified outputs. Invalidated by doc_version_hash."""
from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.db.base import Base, created_at_col, uuid_pk


class AnswerCache(Base):
    __tablename__ = "answer_cache"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    doc_version_hash: Mapped[str] = mapped_column(String(64), index=True)

    normalized_question: Mapped[str] = mapped_column(Text, index=True)  # exact-tier key
    question_embedding: Mapped[list[float] | None] = mapped_column(
        HALFVEC(settings.embedding_dim)
    )  # semantic tier (gated >=0.95)

    answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[list | None] = mapped_column(JSONB)
    tier: Mapped[str] = mapped_column(String(16))  # exact|escalated
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_col()
