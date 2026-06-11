from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at_col, uuid_pk


class RiskReport(Base):
    __tablename__ = "risk_reports"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), unique=True)
    
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|generating|ready|failed
    overall_risk_score: Mapped[str | None] = mapped_column(String(16))  # high|medium|low
    summary: Mapped[str | None] = mapped_column(Text)
    
    risk_count_high: Mapped[int] = mapped_column(Integer, default=0)
    risk_count_medium: Mapped[int] = mapped_column(Integer, default=0)
    risk_count_low: Mapped[int] = mapped_column(Integer, default=0)
    
    risks: Mapped[list | None] = mapped_column(JSONB)  # array of risk items
    
    model: Mapped[str | None] = mapped_column(String(64))
    token_usage: Mapped[dict | None] = mapped_column(JSONB)  # {input, output, cached}
    error_msg: Mapped[str | None] = mapped_column(Text)
    
    created_at: Mapped[datetime] = created_at_col()
    
    document: Mapped["Document"] = relationship(back_populates="risk_report")
