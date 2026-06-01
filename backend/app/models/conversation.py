from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at_col, uuid_pk


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = created_at_col()

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )

    role: Mapped[str] = mapped_column(String(16))  # user|assistant
    content: Mapped[str] = mapped_column(Text)

    citations: Mapped[list | None] = mapped_column(JSONB)  # [{chunk_id,page,section,cited_span,polarity,verified}]
    exceptions: Mapped[list | None] = mapped_column(JSONB)  # carve-outs surfaced
    answerable: Mapped[bool | None] = mapped_column(Boolean)
    missing_context: Mapped[list | None] = mapped_column(JSONB)
    confidence: Mapped[str | None] = mapped_column(String(16))

    model: Mapped[str | None] = mapped_column(String(64))
    tier: Mapped[str | None] = mapped_column(String(16))  # fast|balanced|accurate
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text)

    token_usage: Mapped[dict | None] = mapped_column(JSONB)  # {input,output,cached}
    created_at: Mapped[datetime] = created_at_col()

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
