"""Ingestion orchestrator (run by the arq worker).

receive -> parse -> chunk -> structure -> embed -> persist, updating documents.status at
each stage so the UI can show progress. Any failure -> status=failed + error_msg.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import (
    Chunk,
    CrossRefEdge,
    DefinedTerm,
    Document,
    Embedding,
    GovernanceRecord,
)
from app.services.gemini.client import get_gemini
from app.services.ingestion.chunk import chunk_document
from app.services.ingestion.parse import parse_document
from app.services.ingestion.parse_light import parse_pdf_text
from app.services.ingestion.structure import extract_structures

# Small docs (below this token count) can be cached whole (lazy, short TTL); larger -> RAG.
# Expressed in tokens vs the ~200K Pro tier, not a flat page count.
CACHED_WHOLE_MAX_TOKENS = 150_000


async def ingest_document(db: AsyncSession, document_id: uuid.UUID) -> None:
    doc = await db.get(Document, document_id)
    if doc is None:
        return

    async def set_status(status: str) -> None:
        doc.status = status
        await db.commit()

    try:
        await set_status("parsing")
        parsed = parse_document(doc.storage_uri, doc.mime_type)
        doc.page_count = parsed.page_count

        await set_status("chunking")
        chunks = chunk_document(parsed)
        if not chunks:
            raise ValueError("no chunks produced from document")

        await set_status("structuring")
        structures = extract_structures(chunks)

        await set_status("embedding")
        vectors = await get_gemini().embed([c.content for c in chunks], batch=True)
        if len(vectors) != len(chunks):
            raise ValueError(f"embedding count {len(vectors)} != chunk count {len(chunks)}")

        await _persist(db, doc, chunks, structures, vectors)

        total_tokens = sum(c.token_count for c in chunks)
        doc.strategy = "cached_whole" if total_tokens <= CACHED_WHOLE_MAX_TOKENS else "rag"
        await set_status("ready")
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
        await db.rollback()
        doc.status = "failed"
        doc.error_msg = str(exc)
        await db.commit()
        raise


async def run_rag_ingestion(db: AsyncSession, doc: Document) -> None:
    """RAG fallback ingestion for documents too large for whole-file Gemini attachment.

    Uses the lightweight pypdf text extractor (no Docling/OCR), then the same
    chunk → structure → embed → persist path as the full pipeline. The caller owns
    document status and the strategy flag; this only populates chunks/embeddings/structures.
    """
    parsed = parse_pdf_text(doc.storage_uri)
    doc.page_count = parsed.page_count

    chunks = chunk_document(parsed)
    if not chunks:
        raise ValueError(
            "no extractable text — the document appears to be scanned without an OCR text layer"
        )

    structures = extract_structures(chunks)
    vectors = await get_gemini().embed([c.content for c in chunks], batch=True)
    if len(vectors) != len(chunks):
        raise ValueError(f"embedding count {len(vectors)} != chunk count {len(chunks)}")

    await _persist(db, doc, chunks, structures, vectors)


async def _persist(db, doc, chunks, structures, vectors) -> None:
    """Insert chunks, embeddings, and the ingest-time structures in one transaction."""
    ordinal_to_id: dict[int, uuid.UUID] = {}

    chunk_rows = []
    for c in chunks:
        row = Chunk(
            document_id=doc.id,
            ordinal=c.ordinal,
            content=c.content,
            page_start=c.page_start,
            page_end=c.page_end,
            bbox=c.bbox,
            section_path=c.section_path,
            char_start=c.char_start,
            char_end=c.char_end,
            is_table=c.is_table,
            list_group=c.list_group,
            token_count=c.token_count,
        )
        db.add(row)
        chunk_rows.append((c, row))

    await db.flush()  # populate chunk ids
    for c, row in chunk_rows:
        ordinal_to_id[c.ordinal] = row.id

    for (_c, row), vec in zip(chunk_rows, vectors):
        db.add(Embedding(
            chunk_id=row.id,
            embedding=vec,
            embedding_model=settings.gemini_embedding_model,
            dim=settings.embedding_dim,
            chunking_version=1,
        ))

    for dt in structures.defined_terms:
        db.add(DefinedTerm(
            document_id=doc.id,
            term=dt["term"],
            definition=dt["definition"],
            source_chunk_id=ordinal_to_id.get(dt["source_chunk_ordinal"]),
            depth=dt["depth"],
        ))

    for e in structures.cross_ref_edges:
        target_ord = e["target_chunk_ordinal"]
        db.add(CrossRefEdge(
            document_id=doc.id,
            from_chunk_id=ordinal_to_id[e["from_chunk_ordinal"]],
            target_ref=e["target_ref"],
            target_chunk_id=ordinal_to_id.get(target_ord) if target_ord is not None else None,
            kind=e["kind"],
            confidence=e["confidence"],
            resolved=e["resolved"],
        ))

    for g in structures.governance_records:
        db.add(GovernanceRecord(
            document_id=doc.id,
            kind=g["kind"],
            chunk_id=ordinal_to_id.get(g["chunk_ordinal"]),
            detail=g["detail"],
        ))

    await db.flush()
