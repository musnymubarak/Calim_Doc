"""Reciprocal Rank Fusion — combine dense (pgvector) and BM25 (pg_search) result lists."""
from __future__ import annotations


def rrf_fuse(ranked_lists: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Fuse multiple ranked lists of chunk_ids. Returns [(chunk_id, score)] desc by score.

    score(d) = sum over lists of 1 / (k + rank_in_list(d)).
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
