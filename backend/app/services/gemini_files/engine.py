"""Gemini File API engine: replaces both the RAG pipeline (main) and the NotebookLM spike.

Ingestion = upload the document to the Gemini Files API. Answering = ask Gemini with the file
attached, forcing structured output so every claim carries a verbatim quote + page number.
Gemini does its own document understanding (incl. native PDF/page parsing), so there is no
chunking/embeddings/retrieval here — but it IS an official, stable, multi-user-safe API.

Files expire ~48h server-side, so we re-upload on demand from the locally-stored file.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import Document
from app.services.gemini_files.client import get_gemini_files

logger = logging.getLogger(__name__)

# File-API citation schema: NO chunk_id (no chunk store); the model cites a verbatim quote +
# page from the document it can see directly.
FILE_ANSWER_SCHEMA: dict = {
    "type": "object",
    "required": ["answer", "claims", "answerable", "confidence"],
    "properties": {
        "answer": {"type": "string"},
        "answerable": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "missing_context": {"type": "array", "items": {"type": "string"}},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["claim_text", "cited_quote"],
                "properties": {
                    "claim_text": {"type": "string"},
                    "cited_quote": {"type": "string", "description": "verbatim text from the document"},
                    "page": {"type": "integer"},
                    "section": {"type": "string"},
                    "polarity": {"type": "string", "enum": ["affirmative", "negative"]},
                    "exceptions": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}

SYSTEM_PROMPT = (
    "You answer questions about the attached legal contract using ONLY its contents. "
    "For every factual claim, include the exact verbatim quote it rests on and the page number. "
    "If the contract does not contain the answer, set answerable=false and say what is missing — "
    "never guess. Always surface carve-outs (except/unless/provided that/notwithstanding) in the "
    "relevant claim's exceptions[]. Reason before answering."
)

_TIER_MODEL = {
    "fast": settings.gemini_model_fast,
    "balanced": settings.gemini_model_fast,
    "accurate": settings.gemini_model_accurate,
}


@dataclass
class AnswerResult:
    answer: str
    citations: list = field(default_factory=list)
    exceptions: list = field(default_factory=list)
    answerable: bool | None = None
    missing_context: list = field(default_factory=list)
    confidence: str | None = None
    model: str | None = None
    tier: str | None = None
    escalated: bool = False
    escalation_reason: str | None = None
    token_usage: dict = field(default_factory=dict)


def _expiring_soon(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    now = datetime.now(timezone.utc)
    exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    return exp <= now + timedelta(hours=1)


async def _ensure_uploaded(db: AsyncSession, doc: Document) -> str:
    """Return a live Gemini file name, (re)uploading from the local file if missing/expiring."""
    if doc.gemini_file_name and not _expiring_soon(doc.gemini_file_expires_at):
        return doc.gemini_file_name
    uploaded = await get_gemini_files().upload(doc.storage_uri, doc.mime_type)
    doc.gemini_file_name = uploaded.name
    doc.gemini_file_uri = uploaded.uri
    doc.gemini_file_expires_at = uploaded.expires_at
    await db.commit()
    return uploaded.name


async def ingest_to_gemini(db: AsyncSession, document_id: uuid.UUID) -> None:
    """Upload the document to the Gemini Files API and record its handle."""
    doc = await db.get(Document, document_id)
    if doc is None:
        return
    try:
        doc.status = "processing"
        await db.commit()

        uploaded = await get_gemini_files().upload(doc.storage_uri, doc.mime_type)
        doc.gemini_file_name = uploaded.name
        doc.gemini_file_uri = uploaded.uri
        doc.gemini_file_expires_at = uploaded.expires_at
        doc.status = "ready"
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
        await db.rollback()
        doc.status = "failed"
        doc.error_msg = str(exc)
        await db.commit()
        raise


def _build_citations(claims: list[dict]) -> list[dict]:
    return [
        {
            "claim_text": c.get("claim_text"),
            "quote": c.get("cited_quote"),
            "page": c.get("page"),
            "section": c.get("section"),
            "exceptions": c.get("exceptions") or [],
        }
        for c in (claims or [])
    ]


async def answer_question(
    db: AsyncSession,
    document_id: uuid.UUID,
    question: str,
    tier_override: str | None = None,
) -> AnswerResult:
    doc = await db.get(Document, document_id)
    if doc is None or doc.status != "ready":
        return AnswerResult(
            answer="This document is not ready yet (still uploading to Gemini).",
            answerable=False, confidence="low", tier=tier_override or "fast",
        )

    file_name = await _ensure_uploaded(db, doc)
    tier = tier_override or "fast"
    model = _TIER_MODEL.get(tier, settings.gemini_model_fast)

    gen = await get_gemini_files().answer(
        file_name, question, model=model, system_prompt=SYSTEM_PROMPT,
        schema=FILE_ANSWER_SCHEMA, max_output_tokens=settings.max_output_tokens,
    )
    data = gen.data
    claims = data.get("claims", [])
    return AnswerResult(
        answer=data.get("answer", ""),
        citations=_build_citations(claims),
        exceptions=[e for c in claims for e in (c.get("exceptions") or [])],
        answerable=bool(data.get("answerable", False)),
        missing_context=data.get("missing_context", []),
        confidence=data.get("confidence"),
        model=gen.model, tier=tier,
        token_usage=gen.token_usage,
    )
