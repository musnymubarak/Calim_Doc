# Stack & Build Log

Reference inventory of every technology used and every scaffolding step taken, for later
reference. Companion to [ARCHITECTURE.md](ARCHITECTURE.md) (the design) — this file is the
**tech inventory + build log**.

---

## Technology inventory

### Backend
| Technology | Role | Why this one |
|---|---|---|
| **Python 3.12** | Backend language | Docling + Gemini SDK + ML ecosystem are Python-native |
| **FastAPI** | Web framework / REST + SSE | Async, typed, OpenAPI out of the box |
| **Uvicorn** | ASGI server | Standard FastAPI server |
| **Pydantic v2** + **pydantic-settings** | Schemas + config | Request/response models, env-based settings |
| **SQLAlchemy 2.0 (async)** | ORM | Async engine over asyncpg; mature migrations story |
| **asyncpg** | Postgres driver | Fastest async Postgres driver |
| **Alembic** | DB migrations | Standard with SQLAlchemy |
| **pgvector** (`pgvector` py lib) | Vector columns | `halfvec(768)` for embeddings |
| **arq** | Async job queue | Lightweight Redis-based worker; simpler than Celery |
| **Redis** | Queue broker + cache | Backs arq; also app-level cache if needed |
| **Docling** | Document parsing | PDF/DOCX → structured text + layout + tables; OCR fallback |
| **google-genai** | Gemini SDK | Current official SDK; embeddings + generation + caching |
| **httpx** | HTTP client | Async calls (reranker service, etc.) |
| **python-multipart** | File uploads | Required by FastAPI for multipart form uploads |

### Database
| Technology | Role | Why this one |
|---|---|---|
| **PostgreSQL** | Primary datastore | One DB for relational + vectors + full-text |
| **pgvector** (extension) | Vector search | HNSW index, `halfvec` for 4× less RAM |
| **ParadeDB `pg_search`** (extension) | BM25 full-text | Real BM25 (IDF/TF-sat/length-norm) — `ts_rank` is not enough |
| → image: **`paradedb/paradedb`** | Postgres image | Bundles `pg_search` **and** `pgvector` in one image |

### Retrieval / ML
| Technology | Role | Why this one |
|---|---|---|
| **Self-hosted cross-encoder** | Reranker | Hosted rerankers tested poorly on legal text; runs as a container on the same VPS |
| **gemini-embedding-001** | Embeddings | 768-dim (MRL truncation), Batch API for 50% off |
| **Gemini Flash / Pro (3.x)** | Generation | Flash-first baseline; Pro on escalation |

### Frontend
| Technology | Role | Why this one |
|---|---|---|
| **React 18** + **TypeScript** | UI | Component model + type safety |
| **Vite** | Build tool / dev server | Fast HMR, simple config |
| **react-pdf** (PDF.js) | Document viewer | Render PDF + draw citation bbox overlays |
| **TanStack Query** | Server state | Fetching, caching, polling ingest status |

### Infra / deployment
| Technology | Role | Why this one |
|---|---|---|
| **Docker Compose** | Orchestration | Whole stack on one VPS |
| **Single VPS** | Host | All services + local file volume (no S3) |
| **Local filesystem** | File storage | Behind a `Storage` interface; S3 swappable later |

---

## Build log

> Each step records what was created and why. Append-only.

### Step 0 — Design
- `ARCHITECTURE.md` — full design: schema, ingestion pipeline, escalation ladder, cost
  controls, model strategy, eval harness, build order, deployment notes.
- Two verification workflows informed it (cost optimization + accuracy/cost reconciliation).

### Step 1 — Reference doc
- `STACK.md` (this file) created.

### Step 2 — Root project files
- `docker-compose.yml` — db (ParadeDB), redis, backend, worker, frontend; named volumes
  `pgdata` + `filedata` (raw files on local volume, no S3).
- `.env.example` — Postgres, Gemini key + model registry, file dir, reranker URL, cost guardrails.
- `.gitignore`, `README.md` (run instructions).

### Step 3 — Backend core
- `pyproject.toml` (deps), `Dockerfile` (python:3.12-slim + tesseract/poppler for Docling/OCR).
- `app/config.py` (pydantic-settings), `app/main.py` (FastAPI + CORS + routers + /health).
- `app/db/base.py` (DeclarativeBase + uuid/created_at helpers), `app/db/session.py` (async engine).

### Step 4 — Models (match ARCHITECTURE.md §3)
- `users, documents, chunks, embeddings(halfvec 768), defined_terms, cross_ref_edges,`
  `governance_records, conversations, messages, answer_cache, usage`.

### Step 5 — API routers
- `upload` (multipart + SHA-256 dedup + enqueue), `documents` (list/status), `conversations`,
  `chat` (runs the answer pipeline). `deps.py` = dev user stub (X-User-Email) + arq pool.

### Step 6 — Services
- `storage.py` — **implemented**: `LocalFSStorage` behind a `Storage` Protocol.
- `citations/verify.py` — **implemented**: whitespace-normalized span verification + coverage.
- `retrieval/rrf.py` — **implemented**: Reciprocal Rank Fusion.
- `answers/pipeline.py` — **implemented**: escalation ladder skeleton + `should_escalate` triggers
  + `AnswerResult` (returns a graceful placeholder until generation is wired).
- `gemini/schemas.py` — **implemented**: `ANSWER_SCHEMA` (per-claim cited spans) + system prompt.
- **Stubbed (raise NotImplementedError, clearly marked TODO):** `gemini/client.py` (embed/generate),
  `ingestion/{parse,chunk,structure,pipeline}.py`, `retrieval/hybrid.py`.

### Step 7 — Worker + migrations
- `workers/main.py` — arq `WorkerSettings` + `ingest_document` job.
- Alembic: `alembic.ini`, `env.py` (async, autogenerate), `script.py.mako`,
  `versions/0001_init.py` (creates `vector` + `pg_search` extensions, all tables, HNSW + BM25 indexes).

### Step 8 — Frontend (Vite + React + TS)
- `package.json` (react, @tanstack/react-query, react-pdf), `vite.config.ts`, `tsconfig.json`, `Dockerfile`.
- `api/client.ts` (typed API), `App.tsx` (split view + doc selector + status polling),
  `features/upload` (implemented), `features/chat` (implemented), `features/viewer` (placeholder —
  needs a file-serving endpoint + PDF.js bbox overlay).

### Step 9 — Verification
- `python -m compileall backend/app` → all backend sources compile (syntax-clean).

### Step 10 — Ingestion spine #1: parser + chunker (implemented)
- `ingestion/parse.py` — **implemented**: lazy Docling `DocumentConverter`; flattens
  `iterate_items()` into `ParsedBlock`s with page/bbox, a heading-stack `section_path`,
  char spans into a canonical `full_text`; tables kept atomic (caption + body); consecutive
  list items tagged with a shared `list_group`. Defensive against Docling version drift
  (string label compare, `getattr` provenance, dual table-export arity).
- `ingestion/chunk.py` — **implemented**: groups blocks into indivisible *units* (block /
  whole list group / table), greedily packs to a token budget (default 650, ~15% single-unit
  overlap). Tables emit as their own chunk, alone. **Chunk `content` is the exact
  `full_text[char_start:char_end]` slice → any cited verbatim span substring-matches** (feeds
  the citation gate). `estimate_tokens` is a swappable ~4-char heuristic.
- `tests/test_chunk.py` — **4 invariants pass** (no Docling needed): content == source slice;
  table atomic & alone; list group never split; ordinals sequential.

### Step 11 — Ingestion spine #3 + #4: structures, embeddings, persistence (implemented)
- `ingestion/structure.py` — **implemented** (deterministic regex, no LLM): defined-term map
  (`"X" means …` + parenthetical `(the "X")`), cross-ref graph (explicit `Section/Schedule
  N.N` with best-effort resolution to a chunk via heading number; incorporation-by-reference;
  **relative refs flagged low-confidence & never resolved** — "the foregoing", "notwithstanding
  anything to the contrary", herein/hereof), governance records (precedence / MFN / renewal /
  conflict).
- `gemini/client.py` — **embed() implemented**: google-genai `embed_content`, truncated to
  `EMBEDDING_DIM` (MRL) + unit-normalized, batched, run off the event loop via `to_thread`.
  (`generate()` still stubbed; `batch=True` Batch-API path is a cost TODO.)
- `ingestion/pipeline.py` — **persistence implemented**: parse → chunk → structure → embed →
  one-transaction insert of chunks + embeddings + defined_terms + cross_ref_edges +
  governance_records (ordinal→id mapping); picks `strategy` (`cached_whole` ≤150K tokens else
  `rag`); status transitions + rollback-on-failure.
- `tests/test_structure.py` — **4 tests pass**: defined terms (incl. definition text), explicit
  cross-ref resolves to the right chunk, relative refs flagged & untrusted, governance kinds.

**Verification:** `compileall backend/app backend/tests` clean; 8/8 tests pass
(`test_chunk.py` + `test_structure.py`).

Remaining stubs: `gemini/client.py` `generate()`, `retrieval/hybrid.py`, `answers/pipeline.py`
wiring (+ Batch-API embed path, file-serving endpoint + PDF.js overlay, eval harness, auth).

> Untested at runtime (need the SDK + a real PDF + an API key, unavailable here): Docling
> parsing and the Gemini embed call. Pure-logic pieces (chunker, structure regex) are tested.

### Step 12 — Retrieval + generation + escalation ladder (implemented), reviewed, fixed
- `retrieval/hybrid.py` — dense (pgvector cosine) + BM25 + RRF + self-hosted reranker (HTTP,
  best-effort fallback) + gated injection (definitions/cross-refs/governance), context capped.
- `gemini/client.py` `generate()` — structured JSON output (ANSWER_SCHEMA) + thinking budget.
- `answers/pipeline.py` — full escalation ladder (cache → retrieve → Flash → gates →
  should_escalate → wider+Pro+thinking → persist only verified). `answers/gates.py` —
  carve-out scan + escalation triggers. `tests/test_answers.py` — 13 tests.
- **Adversarial review workflow** (5 dimensions, findings verified vs real library behavior):
  28 findings → **26 false positives, 3 confirmed bugs**. The pgvector/ParadeDB/google-genai/
  SQLAlchemy integration code was confirmed CORRECT as written (several proposed "fixes" would
  have regressed). Fixed all 3 (all in the escalation router): `tier_override` no longer
  bypasses hard safety gates (+ `tier` is a validated Literal); `sparse` (<5 candidates) now
  trips `weak_retrieval`; two-phase assembly stops the token cap from dropping gated injections.

### Step 13 — No-Docker local run: pluggable full-text backend
- **Decision:** local runs use no Docker. `pg_search` (ParadeDB) has no native install path, so
  added `FTS_BACKEND` config: `pg_search` (prod/Docker, true BM25) | `tsvector` (local, Postgres
  built-in `to_tsvector`/`ts_rank`, no extra extension).
- `config.py` (`fts_backend`), `hybrid.py` (`_bm25_ids` branches on backend), `0001_init.py`
  (creates `pg_search`+BM25 index OR a GIN `tsvector` index per backend; `vector` ext always).
- `LOCAL_DEV.md` — native-process setup (recommended WSL2; native-Windows notes for the awkward
  pgvector/Redis bits). README split into "Run locally (no Docker)" vs "Run with Docker (VPS)".

**Verification:** all 21 tests pass; `compileall backend/app` clean.

> Still untested at runtime (no Postgres/SDK/Docling here): Docling parse, Gemini embed/generate,
> all DB I/O (pgvector cosine, both FTS backends), the migration. Confirmed correct by review but
> not executed — first real run on a local stack will shake out any remaining integration gaps.

---

## Status: what's implemented vs stubbed

**Runnable now:** `docker compose up` boots all 5 services; migrations create the schema;
upload → dedup → DB row → enqueue works; chat returns a graceful "pipeline not implemented"
answer. The skeleton, schema, storage, RRF, and citation gate are real.

**To make it actually answer questions, fill these stubs (in build-order priority):**
1. `ingestion/parse.py` — Docling `DocumentConverter` → `ParsedBlock`s (page/bbox/section, atomic tables).
2. `ingestion/chunk.py` — provenance chunker (rules in the file docstring).
3. `ingestion/structure.py` — defined-term map, cross-ref edges, governance records.
4. `ingestion/pipeline.py` — persist chunks/embeddings/structures; pick rag vs cached_whole.
5. `gemini/client.py` — google-genai embed (Batch) + structured generate (ANSWER_SCHEMA, cached prefix).
6. `retrieval/hybrid.py` — dense + BM25 + RRF + rerank + gated injection.
7. `answers/pipeline.py` — wire the ladder (cache → retrieve → generate → gates → escalate → cache).
8. Backend file-serving endpoint + `features/viewer` PDF.js bbox highlight.
9. Eval harness (`services/eval/`) — labeled set + context-recall / false-abstention metrics.

**Pre-launch hardening:** real auth (replace the X-User-Email stub), per-user quotas + global
spend kill-switch (enforce, not just track), tighten CORS, secrets management on the VPS,
disk-space monitoring + off-VPS backups.

