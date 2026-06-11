"""The selective-spend escalation ladder.

(a) cheap baseline: cache -> hybrid retrieve -> Flash (thinking off) -> free gates
(b) triggers (near-free): citation/span gate fails, carve-out trips, answerable=false,
    weak retrieval score-gap, a guard activated, high-stakes clause type, thumbs-down
(c) escalated: wider retrieval -> thinking budget + Pro -> (TODO: independent Flash critic pass)

NEVER gate spend on self-reported confidence or embedding-cosine grounding. Persist only
VERIFIED + answerable answers to the cache.
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.cache import AnswerCache
from app.models.document import Document
from app.services.answers.gates import carve_out_unaddressed, should_escalate
from app.services.citations.verify import verify_answer
from app.services.gemini.client import get_gemini
from app.services.gemini.schemas import SYSTEM_PROMPT
from app.services.retrieval.hybrid import RetrievedChunk, hybrid_retrieve

logger = logging.getLogger(__name__)


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


def _normalize_question(q: str) -> str:
    return re.sub(r"\s+", " ", q).strip().lower()


def _format_context(chunks: list[RetrievedChunk]) -> str:
    return "\n\n".join(
        f"[chunk_id={c.chunk_id} page={c.page_start} section={c.section_path}]\n{c.content}"
        for c in chunks
    )


def _build_citations(
    verified_claims: list[dict], chunk_pages: dict[str, int | None] | None = None
) -> list[dict]:
    """Normalize verified claims into the shape the UI renders (claim_text / quote / page).

    The model fills `claim_text` + `cited_span` but routinely omits the optional `page`, so we
    resolve the page from the chunk the span was verified against (its real page_start) rather
    than trusting the model. Skeletal claims (no text AND no quote) are dropped."""
    chunk_pages = chunk_pages or {}
    out: list[dict] = []
    for c in verified_claims:
        claim_text = (c.get("claim_text") or "").strip()
        quote = (c.get("cited_span") or "").strip()
        if not claim_text and not quote:
            continue
        # Real page from the verified chunk wins over the model's (usually-null) page.
        page = chunk_pages.get(str(c.get("chunk_id")))
        if page is None:
            page = c.get("page")
        out.append({
            "claim_text": claim_text or None,
            "quote": quote or None,
            "cited_span": quote or None,   # kept for back-compat / viewer navigation
            "page": page,
            "section": c.get("section"),
            "polarity": c.get("polarity"),
            "exceptions": c.get("exceptions") or [],
            "chunk_id": c.get("chunk_id"),
            "verified": c.get("verified", False),
        })
    return out


async def _cache_lookup(db, document_id, version_hash, norm_q) -> AnswerResult | None:
    row = (await db.execute(
        select(AnswerCache).where(
            AnswerCache.document_id == document_id,
            AnswerCache.doc_version_hash == version_hash,
            AnswerCache.normalized_question == norm_q,
            AnswerCache.verified.is_(True),
        ).limit(1)
    )).scalar_one_or_none()
    if row is None:
        return None
    return AnswerResult(
        answer=row.answer, citations=row.citations or [], answerable=True,
        confidence="high", tier=row.tier, escalated=(row.tier == "escalated"),
        token_usage={"cached": True},
    )


async def _cache_store(db, document_id, version_hash, norm_q, qvec, result, tier) -> None:
    db.add(AnswerCache(
        document_id=document_id, doc_version_hash=version_hash, normalized_question=norm_q,
        question_embedding=qvec, answer=result.answer, citations=result.citations,
        tier=tier, verified=True,
    ))
    await db.commit()


async def answer_question(
    db: AsyncSession,
    document_id: uuid.UUID,
    question: str,
    tier_override: str | None = None,
) -> AnswerResult:
    doc = await db.get(Document, document_id)
    version_hash = doc.content_hash if doc else ""
    norm_q = _normalize_question(question)

    cached = await _cache_lookup(db, document_id, version_hash, norm_q)
    if cached is not None:
        return cached

    gemini = get_gemini()
    qvec = (await gemini.embed([question], task_type="RETRIEVAL_QUERY"))[0]

    # --- (a) cheap baseline ---
    retrieval = await hybrid_retrieve(db, document_id, qvec, question)
    chunks_by_id = {c.chunk_id: c.content for c in retrieval.chunks}
    gen = await gemini.generate(
        tier=tier_override or "fast", system_prompt=SYSTEM_PROMPT,
        context=_format_context(retrieval.chunks), question=question,
        thinking_budget=0, max_output_tokens=settings.max_output_tokens,
    )
    data = gen.data
    verification = verify_answer(data.get("claims", []), chunks_by_id)
    answerable = bool(data.get("answerable", False))
    carve_bad = carve_out_unaddressed(verification["verified_claims"])

    # --- (b) triggers ---
    reason = should_escalate(
        all_verified=verification["all_verified"] and not carve_bad,
        coverage=verification["coverage"], score_gap=retrieval.score_gap,
        guards=retrieval.guards_activated, answerable=answerable,
        question=question, sparse=retrieval.sparse,
    )

    escalated = False
    escalation_reason = None
    # Structural safety signals always escalate; an explicit cost/tier override may waive ONLY
    # the high-stakes *heuristic*, never a hard verification/answerability/retrieval gate.
    safety_critical = reason is not None and not reason.startswith("high_stakes_clause")
    # --- (c) escalated path: wider retrieval + thinking + Pro ---
    if reason and (safety_critical or not tier_override):
        if tier_override and safety_critical:
            logger.warning("tier_override=%s overridden by safety escalation reason=%s",
                           tier_override, reason)
        escalated, escalation_reason = True, reason
        retrieval = await hybrid_retrieve(db, document_id, qvec, question, candidates=80, top_k=20)
        chunks_by_id = {c.chunk_id: c.content for c in retrieval.chunks}
        gen = await gemini.generate(
            tier="accurate", system_prompt=SYSTEM_PROMPT,
            context=_format_context(retrieval.chunks), question=question,
            thinking_budget=2048, max_output_tokens=settings.max_output_tokens,
        )
        data = gen.data
        verification = verify_answer(data.get("claims", []), chunks_by_id)
        answerable = bool(data.get("answerable", False))
        # TODO: one independent Flash critic pass before clearing high-stakes answers.

    # Map each retrieved chunk to its real page so citations carry a page number even when
    # the model omits the optional `page` field.
    chunk_pages = {str(c.chunk_id): c.page_start for c in retrieval.chunks}
    result = AnswerResult(
        answer=data.get("answer", ""),
        citations=_build_citations(verification["verified_claims"], chunk_pages),
        exceptions=[e for c in verification["verified_claims"] for e in (c.get("exceptions") or [])],
        answerable=answerable,
        missing_context=data.get("missing_context", []),
        confidence=data.get("confidence"),
        model=gen.model, tier=tier_override or ("accurate" if escalated else "fast"),
        escalated=escalated, escalation_reason=escalation_reason,
        token_usage=gen.token_usage,
    )

    # Persist only verified + answerable answers (never cache unverified output).
    if verification["all_verified"] and answerable:
        await _cache_store(
            db, document_id, version_hash, norm_q, qvec, result,
            tier="escalated" if escalated else "exact",
        )

    return result
