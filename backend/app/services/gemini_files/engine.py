"""Gemini File API engine: replaces both the RAG pipeline (main) and the NotebookLM spike.

Ingestion = upload the document to the Gemini Files API. Answering = ask Gemini with the file
attached, forcing structured output so every claim carries a verbatim quote + page number.
Gemini does its own document understanding (incl. native PDF/page parsing), so there is no
chunking/embeddings/retrieval here — but it IS an official, stable, multi-user-safe API.

Files expire ~48h server-side, so we re-upload on demand from the locally-stored file.
"""
from __future__ import annotations

import asyncio
import logging
import re
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
                "required": ["claim_text", "cited_quote", "page"],
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
    "For EVERY factual claim you make, you MUST emit a claim object with a NON-EMPTY "
    "claim_text, a NON-EMPTY cited_quote copied word-for-word from the document (never a "
    "summary or empty string), and the page number that quote appears on. Do not emit "
    "placeholder or empty claims — if you cannot find a supporting verbatim quote for a "
    "statement, leave that statement out of claims[] rather than emitting a blank claim. "
    "Prefer fewer, fully-grounded claims over many empty ones. "
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


async def _ensure_uploaded(db: AsyncSession, doc: Document, force_reupload: bool = False) -> str:
    """Return a live Gemini file name, (re)uploading from the local file if missing/expiring."""
    if doc.gemini_file_name and not force_reupload and not _expiring_soon(doc.gemini_file_expires_at):
        return doc.gemini_file_name
    uploaded = await get_gemini_files().upload(doc.storage_uri, doc.mime_type)
    doc.gemini_file_name = uploaded.name
    doc.gemini_file_uri = uploaded.uri
    doc.gemini_file_expires_at = uploaded.expires_at.replace(tzinfo=None) if uploaded.expires_at else None
    # A fresh file invalidates any context cache built over the old one.
    doc.gemini_cache_name = None
    doc.cache_expires_at = None
    await db.commit()
    return uploaded.name


# Context cache lives ~1h; questions within that window skip re-processing the whole document.
_CACHE_TTL_SECONDS = 3600


async def _ensure_cache(db: AsyncSession, doc: Document, file_name: str, model: str) -> str | None:
    """Return a live context-cache name for (document + SYSTEM_PROMPT) under `model`, creating
    it on demand. Returns None when the document is too small to cache — caller attaches the
    file directly in that case. The cache is created only for the primary model."""
    if doc.gemini_cache_name and not _expiring_soon(doc.cache_expires_at):
        return doc.gemini_cache_name

    from google.genai.errors import ClientError
    try:
        cached = await get_gemini_files().create_cache(
            file_name, model=model, system_prompt=SYSTEM_PROMPT, ttl_seconds=_CACHE_TTL_SECONDS,
        )
    except ClientError as e:
        if e.code == 400:  # below the model's cache-size minimum → skip caching
            logger.info("Doc %s not cacheable (code 400); using direct attach.", doc.id)
            return None
        raise

    doc.gemini_cache_name = cached.name
    doc.cache_expires_at = cached.expires_at.replace(tzinfo=None) if cached.expires_at else None
    await db.commit()
    return cached.name


async def _clear_cache(db: AsyncSession, doc: Document) -> None:
    doc.gemini_cache_name = None
    doc.cache_expires_at = None
    await db.commit()


async def _gemini_can_process(file_name: str, model: str) -> bool:
    """True if Gemini accepts the whole document. A 400 from count_tokens means the file is
    too large to attach in a single request → caller falls back to RAG."""
    from google.genai.errors import ClientError
    try:
        await get_gemini_files().count_tokens(file_name, model=model)
        return True
    except ClientError as e:
        if e.code == 400:
            return False
        raise


async def ingest_to_gemini(db: AsyncSession, document_id: uuid.UUID) -> None:
    """Upload to the Gemini Files API. If the document is too large to attach whole, fall back
    to RAG ingestion (chunk + embed) and mark strategy accordingly."""
    doc = await db.get(Document, document_id)
    if doc is None:
        return
    try:
        doc.status = "processing"
        await db.commit()

        uploaded = await get_gemini_files().upload(doc.storage_uri, doc.mime_type)
        doc.gemini_file_name = uploaded.name
        doc.gemini_file_uri = uploaded.uri
        doc.gemini_file_expires_at = uploaded.expires_at.replace(tzinfo=None) if uploaded.expires_at else None

        if await _gemini_can_process(uploaded.name, settings.gemini_model_fast):
            doc.strategy = "files"
        else:
            # Too large for whole-file attachment → build the retrieval index instead.
            logger.warning("Document %s too large for whole-file Gemini; using RAG fallback.", doc.id)
            from app.services.ingestion.pipeline import run_rag_ingestion
            await run_rag_ingestion(db, doc)
            doc.strategy = "rag"

        doc.status = "ready"
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
        await db.rollback()
        doc.status = "failed"
        doc.error_msg = str(exc)
        await db.commit()
        raise


_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    """Lowercase + collapse whitespace, so quote↔page matching survives PDF line wraps."""
    return _WS.sub(" ", (s or "").lower()).strip()


def _page_index(storage_uri: str, mime_type: str | None) -> list[tuple[int, str]] | None:
    """Return [(page_no, normalized_page_text), ...] for a PDF, or None if unavailable.

    Lets us resolve the real page a cited quote sits on — Gemini's own page numbers for
    attached PDFs are unreliable, so we trust the document text instead."""
    if not mime_type or "pdf" not in mime_type.lower():
        return None
    try:
        from app.services.ingestion.parse_light import parse_pdf_text

        parsed = parse_pdf_text(storage_uri)
    except Exception:  # noqa: BLE001 — page resolution is best-effort, never fatal
        logger.warning("Could not parse %s for page resolution; using model pages.", storage_uri)
        return None
    pages: dict[int, list[str]] = {}
    for b in parsed.blocks:
        pages.setdefault(b.page, []).append(b.text)
    return [(p, _norm(" ".join(texts))) for p, texts in sorted(pages.items())]


def _resolve_page(quote: str, page_index: list[tuple[int, str]] | None, model_page) -> object:
    """Find which page a verbatim quote actually appears on; fall back to the model's page."""
    if page_index and quote:
        needle = _norm(quote)
        if len(needle) >= 12:  # too-short needles match spuriously
            for page_no, text in page_index:
                if needle in text:
                    return page_no
    return model_page


def _build_citations(
    claims: list[dict], page_index: list[tuple[int, str]] | None = None
) -> list[dict]:
    out: list[dict] = []
    for c in (claims or []):
        claim_text = (c.get("claim_text") or "").strip()
        quote = (c.get("cited_quote") or "").strip()
        # Drop skeletal/placeholder claims the model sometimes emits (empty text AND quote).
        if not claim_text and not quote:
            continue
        out.append({
            "claim_text": claim_text or None,
            "quote": quote or None,
            "page": _resolve_page(quote, page_index, c.get("page")),
            "section": c.get("section"),
            "exceptions": c.get("exceptions") or [],
        })
    return out


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

    # Context caching is bound to one model, so use it only for the primary model. Other tiers
    # (or a fallback model) attach the file directly.
    cache_name = None
    if model == settings.gemini_model_fast:
        cache_name = await _ensure_cache(db, doc, file_name, model)

    from google.genai.errors import ClientError
    try:
        gen = await get_gemini_files().answer(
            file_name, question, model=model, system_prompt=SYSTEM_PROMPT,
            schema=FILE_ANSWER_SCHEMA, max_output_tokens=settings.max_output_tokens,
            cached_content=cache_name,
        )
    except ClientError as e:
        if cache_name and e.code in (400, 404):
            # Cache stale/expired → drop it and retry by attaching the file directly.
            logger.warning(f"Context cache {cache_name} invalid (code {e.code}); retrying uncached.")
            await _clear_cache(db, doc)
            gen = await get_gemini_files().answer(
                file_name, question, model=model, system_prompt=SYSTEM_PROMPT,
                schema=FILE_ANSWER_SCHEMA, max_output_tokens=settings.max_output_tokens,
            )
        elif e.code in (400, 403, 404):
            logger.warning(f"Gemini file {file_name} not found/accessible (code {e.code}). Re-uploading...")
            file_name = await _ensure_uploaded(db, doc, force_reupload=True)
            cache_name = await _ensure_cache(db, doc, file_name, model) if model == settings.gemini_model_fast else None
            gen = await get_gemini_files().answer(
                file_name, question, model=model, system_prompt=SYSTEM_PROMPT,
                schema=FILE_ANSWER_SCHEMA, max_output_tokens=settings.max_output_tokens,
                cached_content=cache_name,
            )
        else:
            raise

    data = gen.data
    claims = data.get("claims", [])
    # Resolve each cited quote to its real page from the document text (Gemini's own page
    # numbers for attached PDFs are unreliable). Best-effort: None index → keep model pages.
    page_index = await asyncio.to_thread(_page_index, doc.storage_uri, doc.mime_type)
    return AnswerResult(
        answer=data.get("answer", ""),
        citations=_build_citations(claims, page_index),
        exceptions=[e for c in claims for e in (c.get("exceptions") or [])],
        answerable=bool(data.get("answerable", False)),
        missing_context=data.get("missing_context", []),
        confidence=data.get("confidence"),
        model=gen.model, tier=tier,
        token_usage=gen.token_usage,
    )
