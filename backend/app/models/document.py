"""Documents and the ingest-time structures that back citation fidelity."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Boolean, Date, ForeignKey, Integer, Real, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.db.base import Base, created_at_col, uuid_pk


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)

    filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(128))
    page_count: Mapped[int | None] = mapped_column(Integer)

    storage_uri: Mapped[str] = mapped_column(Text)  # local FS path on the VPS volume
    content_hash: Mapped[str] = mapped_column(String(64), index=True)  # SHA-256 of blob
    text_hash: Mapped[str | None] = mapped_column(String(64))  # normalized-text hash

    doc_version: Mapped[str | None] = mapped_column(String(64))
    doc_role: Mapped[str | None] = mapped_column(String(32))  # base|amendment|restatement|schedule|exhibit
    effective_date: Mapped[date | None] = mapped_column(Date)
    amendment_order: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    error_msg: Mapped[str | None] = mapped_column(Text)

    strategy: Mapped[str] = mapped_column(String(16), default="rag")  # rag|cached_whole
    gemini_cache_name: Mapped[str | None] = mapped_column(String(256))
    cache_expires_at: Mapped[datetime | None]

    # NotebookLM engine (spike, abandoned): the doc was uploaded as a source into a notebook.
    notebooklm_notebook_id: Mapped[str | None] = mapped_column(String(128))
    notebooklm_source_id: Mapped[str | None] = mapped_column(String(128))

    # Gemini File API engine (active): the doc is uploaded to the Files API. Files expire ~48h,
    # so we store the resource name + expiry and re-upload on demand from the local file.
    gemini_file_name: Mapped[str | None] = mapped_column(String(256))   # "files/abc123"
    gemini_file_uri: Mapped[str | None] = mapped_column(Text)
    gemini_file_expires_at: Mapped[datetime | None]

    created_at: Mapped[datetime] = created_at_col()

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)

    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)  # also used to verify citations

    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[dict | None] = mapped_column(JSONB)  # [{page,x0,y0,x1,y1}]
    section_path: Mapped[str | None] = mapped_column(Text)  # "4.2 > Indemnification"
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)

    is_table: Mapped[bool] = mapped_column(Boolean, default=False)
    list_group: Mapped[str | None] = mapped_column(String(64))  # (a)-(z)/(i)-(x) groups
    token_count: Mapped[int | None] = mapped_column(Integer)

    document: Mapped[Document] = relationship(back_populates="chunks")
    embedding: Mapped["Embedding"] = relationship(back_populates="chunk", uselist=False)


class Embedding(Base):
    __tablename__ = "embeddings"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunks.id"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(HALFVEC(settings.embedding_dim))
    embedding_model: Mapped[str] = mapped_column(String(64))
    dim: Mapped[int] = mapped_column(Integer)
    chunking_version: Mapped[int] = mapped_column(Integer, default=1)

    chunk: Mapped[Chunk] = relationship(back_populates="embedding")


class DefinedTerm(Base):
    """`term -> definition` map built at ingest (handles nested terms, depth-capped)."""

    __tablename__ = "defined_terms"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    term: Mapped[str] = mapped_column(Text, index=True)
    definition: Mapped[str] = mapped_column(Text)
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id"))
    depth: Mapped[int] = mapped_column(Integer, default=0)


class CrossRefEdge(Base):
    """Cross-reference graph. Relative refs are flagged, not trusted."""

    __tablename__ = "cross_ref_edges"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    from_chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id"))
    target_ref: Mapped[str] = mapped_column(Text)  # "Section 12.3", "Schedule B"
    target_chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id"))
    kind: Mapped[str] = mapped_column(String(32))  # explicit|relative|incorporation
    confidence: Mapped[float] = mapped_column(Real, default=0.0)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class GovernanceRecord(Base):
    """Precedence / MFN / conflict / renewal clauses detected at ingest."""

    __tablename__ = "governance_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # precedence|MFN|conflict|renewal
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id"))
    detail: Mapped[str | None] = mapped_column(Text)
