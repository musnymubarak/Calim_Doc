"""Retrieval-fed risk report for RAG-routed (oversized) documents.

The whole-file risk path attaches the document to Gemini; that fails for docs too large to
attach. Here we instead retrieve the clauses most relevant to each standard risk category,
assemble a page-tagged context, and run the same RISK_REPORT_SCHEMA generation over text.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.gemini.client import GenResult, get_gemini
from app.services.ingestion.chunk import estimate_tokens
from app.services.retrieval.hybrid import hybrid_retrieve
from app.services.risk.schemas import RISK_REPORT_SCHEMA, RISK_SYSTEM_PROMPT

# Seed queries mirror the risk categories in RISK_SYSTEM_PROMPT; their retrieved clauses are
# unioned so the report sees the high-stakes provisions even though the doc isn't attached whole.
_RISK_QUERIES = [
    "limitation of liability and indemnification",
    "termination for cause or convenience and breach",
    "intellectual property ownership and assignment",
    "payment terms schedule and late payment",
    "confidentiality and data privacy obligations",
    "warranties representations and guarantees",
    "force majeure and excuse of performance",
    "governing law jurisdiction and dispute resolution",
    "non-compete non-solicitation and exclusivity",
]

# Broad coverage budget for the report context (the report wants the whole risk surface, not
# just one query's top-k). Flash handles this comfortably.
_CONTEXT_TOKEN_BUDGET = 24_000


async def generate_rag_report_data(
    db: AsyncSession, document_id: uuid.UUID, *, model: str, max_output_tokens: int
) -> GenResult:
    gemini = get_gemini()

    # Embed all seed queries in one batched call, then retrieve per query and union by chunk_id.
    qvecs = await gemini.embed(_RISK_QUERIES, task_type="RETRIEVAL_QUERY")

    seen: set[str] = set()
    collected: list = []  # RetrievedChunk, dedup'd across queries
    for qvec, q in zip(qvecs, _RISK_QUERIES):
        retrieval = await hybrid_retrieve(db, document_id, qvec, q, candidates=30, top_k=6)
        for ch in retrieval.chunks:
            if ch.chunk_id not in seen:
                seen.add(ch.chunk_id)
                collected.append(ch)

    # Order by page for a coherent read-through, then cap to the context budget.
    collected.sort(key=lambda c: (c.page_start if c.page_start is not None else 1_000_000))
    context_parts: list[str] = []
    used = 0
    for ch in collected:
        toks = estimate_tokens(ch.content)
        if context_parts and used + toks > _CONTEXT_TOKEN_BUDGET:
            break
        page = ch.page_start if ch.page_start is not None else "?"
        section = ch.section_path or ""
        context_parts.append(f"[page={page} section={section}]\n{ch.content}")
        used += toks

    context = "\n\n".join(context_parts)
    prompt = (
        "Analyze the following contract excerpts for risks. Each excerpt is tagged with its "
        "page number — use it for the `page` field of each risk. Excerpts are the clauses most "
        "relevant to standard risk categories; if a protective clause appears entirely absent "
        "from them, you may flag it as a missing-clause risk.\n\n"
        f"CONTRACT EXCERPTS:\n{context}"
    )

    return await gemini.generate_json(
        model=model,
        system_prompt=RISK_SYSTEM_PROMPT,
        prompt=prompt,
        schema=RISK_REPORT_SCHEMA,
        max_output_tokens=max_output_tokens,
    )
