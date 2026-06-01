"""Initial schema: extensions, tables, vector + BM25 indexes.

Revision ID: 0001_init
Revises:
Create Date: 2026-06-01
"""
from __future__ import annotations

from alembic import op

from app.config import settings
from app.models import Base

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # pgvector is always required. pg_search only when that FTS backend is selected.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    if settings.fts_backend == "pg_search":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_search")

    # Tables from model metadata (bootstrap; switch to autogenerate for later revisions).
    Base.metadata.create_all(bind=bind)

    # Vector index (HNSW over halfvec, cosine).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_embeddings_hnsw "
        "ON embeddings USING hnsw (embedding halfvec_cosine_ops)"
    )

    # Full-text index — match the configured backend.
    if settings.fts_backend == "pg_search":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_chunks_bm25 "
            "ON chunks USING bm25 (id, content) WITH (key_field='id')"
        )
    else:  # tsvector (vanilla Postgres)
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_chunks_tsv "
            "ON chunks USING gin (to_tsvector('english', content))"
        )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP INDEX IF EXISTS ix_chunks_tsv")
    op.execute("DROP INDEX IF EXISTS ix_chunks_bm25")
    op.execute("DROP INDEX IF EXISTS ix_embeddings_hnsw")
    Base.metadata.drop_all(bind=bind)
