# Token & Latency Optimization Roadmap

Strategies to reduce Gemini token usage and answer latency while preserving accuracy.
Ranked by impact. Context: free/billed all-Flash tier (`gemini-2.5-flash` primary), shared VPS.

| # | Strategy | Token saving | Latency | Accuracy risk | Status |
|---|----------|--------------|---------|---------------|--------|
| 1 | **Context caching** (whole-file path) | ~75% off input | none | none | ✅ done |
| 2 | **RAG instead of whole-file** — lower the size threshold so medium docs also chunk | ~97k → ≤12k input (**~8×**) | big drop (small context) | Some, on "list *all* X" global questions | proposed |
| 3 | **Answer cache** (normalized question) — repeat/near-identical questions return instantly | ~100% on hits | instant on hit | none (serves only prior verified answers) | built for RAG path, not wired to files |
| 4 | **Trim output** — cap claims to top N + shorter verbatim quotes (structured JSON is the latency driver once context is small) | ~30–50% output | moderate | low (fewer redundant citations) | proposed |
| 5 | **Streaming responses** | none | huge *perceived* drop | none | proposed |
| 6 | **Model tiering** — cheap model first, escalate only on gate failure | varies | varies | none (gates guard it) | already in RAG path |

## Implementation notes (for when we pick these up)

### #1 Context caching — DONE
- `services/gemini_files/client.py`: `create_cache()` + `cached_content` arg on `answer()`.
- `services/gemini_files/engine.py`: `_ensure_cache()` / `_clear_cache()`; cache = document +
  `SYSTEM_PROMPT`, TTL 1h, bound to the primary model only; invalidated on file re-upload;
  falls back to direct attach if the cache is stale (400/404).
- Verified: ~97k input tokens bill at the cached rate on every chat question.
- **Caveat learned:** caching cuts *cost*, not *latency* (~30s) — the model still attends over
  the full 97k-token document during decode. The latency lever is **context size** (→ #2).

### #2 RAG threshold
- Today only docs Gemini can't attach whole (count_tokens 400) route to RAG (`strategy="rag"`).
- Add a configurable token threshold (e.g. `RAG_MAX_WHOLE_FILE_TOKENS`); docs above it use the
  RAG pipeline even if Gemini *could* attach them. Decide via the `count_tokens` value already
  computed at ingest in `ingest_to_gemini`.
- Mitigate the "list all X" accuracy gap: higher `top_k`, multi-query retrieval.

### #3 Answer cache for the files path
- `AnswerCache` model + `_cache_lookup`/`_cache_store` already exist and are used by the RAG
  pipeline (`services/answers/pipeline.py`). Wire the same normalized-question lookup/store into
  `services/gemini_files/engine.answer_question`. Store only verified+answerable answers.
- Zero accuracy risk (serves only previously generated answers); keyed on doc content hash so a
  re-uploaded/changed doc misses the stale cache.

### #4 Trim output
- Structured JSON with long verbatim quotes dominates latency once context is small.
- Cap `claims[]` to top N, cap `cited_quote` length in the schema/prompt.

### #5 Streaming
- Use streaming generation + SSE to the frontend chat. No token saving, large perceived-latency
  win. Structured-output streaming needs incremental JSON handling.

### #6 Model tiering
- RAG pipeline already escalates only on gate failure (cheap Flash → accurate + thinking).
- The whole-file path is single-shot; could add a cheap-first/escalate-on-low-confidence step.

## Memory footprint note (measured)
RAG adds ~7 MB/doc in Postgres (chunks + embeddings + indexes); RAM stays flat (worker ~58 MB —
no resident ML model, since we use pypdf + API embeddings, not Docling). At-scale concern is total
DB/vector-index growth across many large docs on the shared 7.8 GB VPS, not per-request memory.
See [[calim-doc-large-pdf-rag-fallback]].
