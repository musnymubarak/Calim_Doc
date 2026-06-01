"""Hybrid retrieval: pgvector (dense) + pg_search (BM25), RRF-fused, reranked, then gated
injection of definitions / cross-refs / precedence records.

Returns the assembled context (capped to MAX_CONTEXT_TOKENS) plus retrieval signals used by
the escalation router (RRF score-gap — RELATIVE gap, not an absolute cosine cutoff).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import Chunk, CrossRefEdge, DefinedTerm, Embedding, GovernanceRecord
from app.services.ingestion.chunk import estimate_tokens
from app.services.retrieval.rrf import rrf_fuse


@dataclass
class RetrievedChunk:
    chunk_id: str
    content: str
    page_start: int | None
    section_path: str | None
    score: float


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    score_gap: float = 0.0          # rank1 - rank5 RRF gap → weak-retrieval signal
    guards_activated: list[str] = field(default_factory=list)
    sparse: bool = False            # fewer than 5 fused candidates → thin coverage


async def _dense_ids(db, document_id, qvec, limit) -> list[str]:
    dist = Embedding.embedding.cosine_distance(qvec)
    rows = await db.execute(
        select(Chunk.id)
        .join(Embedding, Embedding.chunk_id == Chunk.id)
        .where(Chunk.document_id == document_id)
        .order_by(dist)
        .limit(limit)
    )
    return [str(r) for r in rows.scalars().all()]


_BM25_PG_SEARCH = text(
    # ParadeDB pg_search: @@@ runs the BM25 match; paradedb.score(<key>) ranks it.
    "SELECT id FROM chunks "
    "WHERE document_id = :doc AND content @@@ :q "
    "ORDER BY paradedb.score(id) DESC LIMIT :lim"
)
_BM25_TSVECTOR = text(
    # Postgres built-in FTS fallback (no extension). Lower quality than true BM25 but runs
    # on vanilla Postgres for local/no-Docker runs.
    "SELECT id FROM chunks "
    "WHERE document_id = :doc "
    "AND to_tsvector('english', content) @@ plainto_tsquery('english', :q) "
    "ORDER BY ts_rank(to_tsvector('english', content), plainto_tsquery('english', :q)) DESC "
    "LIMIT :lim"
)


async def _bm25_ids(db, document_id, question, limit) -> list[str]:
    stmt = _BM25_PG_SEARCH if settings.fts_backend == "pg_search" else _BM25_TSVECTOR
    rows = await db.execute(stmt, {"doc": str(document_id), "q": question, "lim": limit})
    return [str(r) for r in rows.scalars().all()]


async def _load_chunks(db, ids: list[str]) -> dict[str, Chunk]:
    if not ids:
        return {}
    uuids = [uuid.UUID(i) for i in ids]
    rows = await db.execute(select(Chunk).where(Chunk.id.in_(uuids)))
    return {str(c.id): c for c in rows.scalars().all()}


async def _rerank(question: str, ids: list[str], chunk_map: dict[str, Chunk]) -> list[str]:
    """Self-hosted cross-encoder. Falls back to the RRF order if the service is unavailable."""
    passages = [{"id": cid, "text": chunk_map[cid].content} for cid in ids if cid in chunk_map]
    if not passages:
        return ids
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.reranker_url}/rerank",
                json={"query": question, "passages": passages},
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
        ordered = [r["id"] for r in sorted(results, key=lambda r: r.get("score", 0.0), reverse=True)]
        seen = set(ordered)
        return ordered + [cid for cid in ids if cid not in seen]
    except Exception:  # noqa: BLE001 — reranker is best-effort; degrade to RRF order
        return ids


async def _gated_injection(
    db, document_id, top_ids: list[str], chunk_map: dict[str, Chunk],
    guards: list[str], cap: int = 3,
) -> list[str]:
    """Inject a definition / cross-ref target / precedence record only when its trigger fires."""
    injected: list[str] = []
    top_set = set(top_ids)
    top_text = " ".join(
        chunk_map[c].content.lower() for c in top_ids if c in chunk_map
    )

    # Definitions: inject the defining chunk only if the term actually appears in retrieved text.
    terms = (await db.execute(
        select(DefinedTerm).where(DefinedTerm.document_id == document_id)
    )).scalars().all()
    for t in terms:
        if len(injected) >= cap:
            break
        src = str(t.source_chunk_id) if t.source_chunk_id else None
        if src and src not in top_set and src not in injected and t.term:
            if re.search(rf"\b{re.escape(t.term.lower())}\b", top_text):
                injected.append(src)

    # Cross-refs: follow only explicit, resolved, high-confidence edges from retrieved chunks.
    edges = (await db.execute(
        select(CrossRefEdge).where(
            CrossRefEdge.document_id == document_id,
            CrossRefEdge.kind == "explicit",
            CrossRefEdge.resolved.is_(True),
            CrossRefEdge.confidence >= 0.9,
        )
    )).scalars().all()
    for e in edges:
        if len(injected) >= cap:
            break
        tgt = str(e.target_chunk_id) if e.target_chunk_id else None
        if str(e.from_chunk_id) in top_set and tgt and tgt not in top_set and tgt not in injected:
            injected.append(tgt)
            guards.append("cross_ref")

    # Governance: flag (don't necessarily inject) when a precedence/conflict clause is in scope.
    gov = (await db.execute(
        select(GovernanceRecord).where(GovernanceRecord.document_id == document_id)
    )).scalars().all()
    for g in gov:
        if g.chunk_id and str(g.chunk_id) in top_set:
            guards.append(g.kind)
            break

    return injected


async def hybrid_retrieve(
    db: AsyncSession,
    document_id: uuid.UUID,
    question_embedding: list[float],
    question: str,
    *,
    candidates: int = 50,
    top_k: int = 10,
) -> RetrievalResult:
    dense = await _dense_ids(db, document_id, question_embedding, candidates)
    bm25 = await _bm25_ids(db, document_id, question, candidates)

    fused = rrf_fuse([dense, bm25])              # [(chunk_id, score)] desc
    fused_score = dict(fused)
    candidate_ids = [cid for cid, _ in fused[:candidates]]

    chunk_map = await _load_chunks(db, candidate_ids)
    reranked = await _rerank(question, candidate_ids, chunk_map)
    top_ids = reranked[:top_k]

    fused_len = len(fused)
    scores = [s for _, s in fused]
    if fused_len >= 5:
        score_gap = scores[0] - scores[4]
    elif scores:
        score_gap = scores[0] - scores[-1]   # gap over available candidates
    else:
        score_gap = 0.0

    guards: list[str] = []
    injected = await _gated_injection(db, document_id, top_ids, chunk_map, guards)

    # Load any injected chunks not already in the candidate map.
    missing = [i for i in injected if i not in chunk_map]
    chunk_map.update(await _load_chunks(db, missing))

    injected_ids = [i for i in injected if i not in top_ids]
    out: list[RetrievedChunk] = []

    def _tokens(cid: str) -> int:
        ch = chunk_map.get(cid)
        return (ch.token_count or estimate_tokens(ch.content)) if ch else 0

    def _emit(cid: str) -> None:
        ch = chunk_map.get(cid)
        if ch is None:
            return
        out.append(RetrievedChunk(
            chunk_id=cid,
            content=ch.content,
            page_start=ch.page_start,
            section_path=ch.section_path,
            score=fused_score.get(cid, 0.0),
        ))

    # Reserve budget for structurally-gated injections (bounded — _gated_injection caps at 3),
    # cap ONLY the retrieved chunks, then always include the injected ones so a gated
    # definition / cross-ref target is never silently dropped by the token cap.
    reserved = sum(_tokens(i) for i in injected_ids)
    cap_for_retrieved = max(0, settings.max_context_tokens - reserved)

    used = 0
    for cid in top_ids:
        if cid not in chunk_map:
            continue
        tokens = _tokens(cid)
        if out and used + tokens > cap_for_retrieved:
            break
        _emit(cid)
        used += tokens
    for cid in injected_ids:
        if cid in chunk_map:
            _emit(cid)
            used += _tokens(cid)

    return RetrievalResult(
        chunks=out, score_gap=score_gap, guards_activated=guards, sparse=(fused_len < 5)
    )
