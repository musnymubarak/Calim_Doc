# Calim_Doc — System Architecture & Technical Writeup

**Contract Intelligence platform** — upload a legal contract, get a grounded, citation-backed Q&A chat plus an automated risk report. This document describes the **current, wired flow** only. Stubbed/abandoned paths (NotebookLM, standalone reranker, Docling parser, the nginx `/events` route) are called out at the end but excluded from the main diagrams.

---

## 1. High-Level Overview

| Concern | Choice |
|---|---|
| **Frontend** | React 18 SPA (Vite, TanStack Query, TypeScript) — 3-panel resizable UI |
| **API** | FastAPI (async, Python 3.12) |
| **Background jobs** | arq workers on Redis |
| **Database** | PostgreSQL via ParadeDB image (pgvector `halfvec[768]` + `pg_search`/BM25) |
| **Object/file storage** | Local filesystem volume (`/data/files`), content-addressed |
| **LLM** | Google **Gemini** — Files API (primary) + embeddings; chat/risk via structured output |
| **Gateway** | nginx reverse proxy, single public port **8015** |
| **Deployment** | Single VPS, Docker Compose, 6 containers |

**Two engines, picked per-document at ingest time:**
- **`files` strategy (primary)** — the whole PDF is uploaded to the Gemini Files API and attached to every question. No chunking, no vector search. Gemini reads the entire document and returns structured, verbatim-quoted claims.
- **`rag` strategy (fallback)** — only when a document is too large for Gemini to attach. The doc is parsed, chunked, embedded, and stored in Postgres; questions run a hybrid-retrieval + escalation pipeline.

---

## 2. Deployment Topology

```
                            Internet
                               │
                               ▼  :8015 (only exposed port)
                    ┌──────────────────────┐
                    │   nginx (alpine)     │   client_max_body_size 200M
                    │   reverse proxy      │   proxy_read_timeout 300s
                    └─────────┬────────────┘
              /documents      │      /  (catch-all)
              /conversations  │      everything else
              /health /docs   │
                    ┌─────────┴───────────┐
                    ▼                     ▼
        ┌────────────────────┐   ┌────────────────────┐
        │ backend            │   │ frontend           │
        │ FastAPI :8000      │   │ Vite dev :5173     │
        │ uvicorn --reload   │   │ React 18 SPA       │
        └───┬────────────┬───┘   └────────────────────┘
            │            │
   DATABASE_URL      REDIS_URL ──────────────┐
            │            │                    │
            ▼            ▼                    ▼
   ┌────────────┐  ┌──────────┐      ┌────────────────────┐
   │ db         │  │ redis 7  │◄─────│ worker             │
   │ ParadeDB   │  │ queue +  │ arq  │ arq WorkerSettings │
   │ (PG16 +    │  │ cache    │ jobs │ ingest_document    │
   │ pgvector + │  └──────────┘      │ generate_risk_..   │
   │ pg_search) │                    └─────────┬──────────┘
   └─────┬──────┘                              │
         │                                     │
   volume: pgdata          shared volume: filedata (/data/files)
                            (backend + worker both mount it)
                                     │
                                     ▼
                          ┌────────────────────┐
                          │  Google Gemini API │  (only external dep)
                          │  • Files API       │
                          │  • generate_content│
                          │  • embeddings      │
                          └────────────────────┘
```

**Containers:** `nginx`, `frontend`, `backend`, `worker`, `db`, `redis`. Only nginx is published (`8015:8015`); everything else is internal. `backend` and `worker` share the **same image and the same `filedata` volume** so the worker can read uploaded bytes.

**Deployed model config (`.env`) — all-Flash free tier:**
`GEMINI_MODEL_FAST = GEMINI_MODEL_ACCURATE = GEMINI_MODEL_FALLBACK = gemini-2.5-flash`; embeddings `gemini-embedding-001` @ 768 dims; `FTS_BACKEND=pg_search`. The "accurate/Pro" escalation tier exists in code but currently resolves to Flash in production.

---

## 3. Request Flow A — Upload & Ingestion (async)

```
USER picks file in UploadPanel
   │  POST /documents/upload  (multipart, X-User-Email header)
   ▼
backend: upload.py
   ├─ SHA-256 content hash → dedupe by (user_id, content_hash)
   ├─ save bytes → /data/files/{user}/{hash}.{ext}
   ├─ insert Document(status="uploaded")
   └─ enqueue arq job → ingest_document(document_id)
   │
   ▼ (Redis queue)
worker: ingest_document
   │  ingest_to_gemini(doc)
   ├─ upload file → Gemini Files API (poll until ACTIVE)
   ├─ preflight count_tokens(model)
   │      ├─ OK ───────────────► strategy = "files"        (PRIMARY)
   │      └─ ClientError 400 ──► strategy = "rag" + run_rag_ingestion()  (FALLBACK)
   ├─ Document.status = "ready"
   └─ enqueue arq job → generate_risk_report(document_id)
   │
   ▼
worker: generate_risk_report
   └─ writes RiskReport row (status: generating → ready/failed)

Meanwhile the frontend polls GET /documents every 3s to watch
status (uploaded→ready) and report_status (pending→ready).
```

### RAG-fallback ingestion (large docs only)
`parse_light.py` (pypdf, text-only — no OCR) → structure-aware **chunking** (~650 tokens, 15% overlap, tables/lists kept atomic) → deterministic regex **structure extraction** (defined terms, cross-references, governance clauses — *no LLM cost*) → **embed** chunks via `gemini-embedding-001` → persist `Chunk` + `Embedding(halfvec[768])` + structures in one transaction.

---

## 4. Request Flow B — Chat Q&A (sync request/response)

```
USER asks question in ChatPanel
   │  (on doc select: POST /conversations → conversation_id)
   │  POST /conversations/{id}/messages  { question, tier? }
   ▼
backend: chat.py
   ├─ verify ownership, persist user Message
   └─ answer_router.answer_question(doc, question, tier)
            │
   ┌────────┴───────────────────────────────┐
   │ strategy == "files"   │ strategy == "rag"
   ▼                       ▼
GEMINI FILES ENGINE        RAG ESCALATION PIPELINE
 ├ ensure file uploaded     ├ normalize Q → AnswerCache lookup (hit → return)
 │   (re-upload if          ├ embed question (RETRIEVAL_QUERY)
 │    expiring ~48h)        ├ hybrid_retrieve: pgvector + BM25 → RRF fuse
 ├ optional context cache   │   → (rerank) → gated injection of defined terms /
 │   (Flash, ~1h TTL)       │      cross-refs / governance
 ├ generate_content with    ├ BASELINE: Flash, thinking OFF, structured schema
 │   FILE_ANSWER_SCHEMA     ├ verify_answer: every cited span must substring-match
 │   (verbatim claims)      │   a retrieved chunk; carve-out gate
 ├ resolve quotes → real    ├ should_escalate?  (citation fail / weak retrieval /
 │   PDF page numbers       │   not answerable / guard / high-stakes clause)
 └ AnswerResult            ├ ESCALATED: wider retrieve + Pro + thinking(2048), re-verify
                            └ cache store ONLY if verified AND answerable
   │                       │
   └───────────┬───────────┘
               ▼
   persist assistant Message (answer, citations[], exceptions[],
       answerable, confidence, model, tier, escalated, token_usage)
               │
               ▼
   frontend renders answer + collapsible citations;
   clicking a citation jumps the PDF iframe to that page (#page=N)
```

**Citation fidelity is the core invariant.** Both engines force structured JSON output where every claim must carry a **verbatim quote** from the source. The RAG path additionally *verifies* spans against chunk text before trusting/caching an answer; the Files path relies on Gemini's grounding to the attached document and resolves quotes back to real page numbers locally via pypdf.

---

## 5. Request Flow C — Risk Report

Auto-triggered after ingestion, or manually via `POST /documents/{id}/report/regenerate` (frontend "Deep Analysis" button can request the `accurate` tier).

- **`files` strategy:** attach whole doc → single Gemini call with `RISK_REPORT_SCHEMA` (overall score, summary, per-risk: category/severity/clause/quote/page/recommendation).
- **`rag` strategy:** 9 seeded risk-category queries → hybrid-retrieve ~6 chunks each → union, sort by page, cap at 24k-token budget → one Gemini call over the assembled excerpts.

Result persisted to the `RiskReport` table. Frontend `RiskReportPanel` polls `GET /documents/{id}/report` every 3s while `pending`/`generating`.

---

## 6. API Surface (current)

| Method | Path | Purpose |
|---|---|---|
| POST | `/documents/upload` | Upload file, dedupe, enqueue ingestion |
| GET | `/documents` | List user's docs + status (polled every 3s) |
| GET | `/documents/{id}` | Single doc detail |
| GET | `/documents/{id}/file` | Stream raw file for the PDF viewer |
| POST | `/conversations` | Create a chat session for a document |
| GET | `/conversations` | List conversations |
| POST | `/conversations/{id}/messages` | Ask a question → routed answer |
| GET | `/documents/{id}/report` | Fetch risk report status + data |
| POST | `/documents/{id}/report/regenerate` | Re-run risk analysis (tier selectable) |
| GET | `/health` | Liveness |

**Auth is a dev stub:** every request carries `X-User-Email` (frontend hardcodes `dev@local`); the backend auto-creates the user. Must be replaced before production.

---

## 7. Data Model (active tables)

```
User ──< Document ──< Conversation ──< Message
                 │
                 ├──1:1── RiskReport
                 │
                 └──(rag only)──< Chunk ──1:1── Embedding(halfvec[768])
                                  │
                                  └─ DefinedTerm / CrossRefEdge / GovernanceRecord

AnswerCache   (rag only: verified Q&A, keyed by doc version hash + normalized question)
Usage         (token/cost accounting per call; quota enforcement not yet wired)
```

Key `Document` fields driving the flow: `status`, `strategy` (`files`|`rag`), `content_hash` (dedupe), `gemini_file_name` / `gemini_file_expires_at` (Files API handle + 48h expiry tracking).

---

## 8. LLM Integration Details

- **SDK:** `google-genai`, sync calls wrapped in `asyncio.to_thread()` (FastAPI is async).
- **Structured output everywhere:** answers and risk reports use forced `response_schema` JSON — no free-text parsing.
- **Retry & fallback** (`gemini/retry.py`): up to 6 attempts with exponential backoff on transient errors (5xx / 429); a model-fallback ladder (Pro → Flash → Flash-Lite → configured fallback) degrades gracefully when the primary is unavailable.
- **Cost controls:** context caching on the Files path (~1h TTL, Flash only), Flash-first with thinking disabled on the cheap path, answer caching on the RAG path, and config guardrails (`MAX_CONTEXT_TOKENS=12k`, `MAX_OUTPUT_TOKENS=8192`, daily spend / per-user token limits — limits tracked, not yet enforced).

---

## 9. Frontend Structure

React 18 SPA, no router — single screen driven by component state in `App.tsx`:

- **Left sidebar:** document list (3s polling) + `UploadPanel`.
- **Center:** `DocumentViewer` — native browser PDF viewer in an `<iframe>` (`#page=N` deep-links for citations). *Note: `react-pdf` is installed but unused.*
- **Right panel:** tabbed `ChatPanel` (Q&A + citation accordion + token badges) / `RiskReportPanel` (score, summary, collapsible risk cards).
- All panel widths are drag-resizable and persisted to `localStorage`.
- Data layer: **TanStack Query** (polling, caching). All calls are **blocking request/response — no streaming/WebSockets.**

---

## 10. Not in the current flow (excluded)

- **NotebookLM engine** — fully abandoned; service commented out in compose, config retained but no code path reaches it.
- **Standalone reranker** (`RERANKER_URL`) — referenced by the RAG retriever but **not deployed** in compose; retrieval silently falls back to RRF order if absent.
- **Docling parser** (`parse.py`) — the heavyweight layout/OCR parser is not called; RAG fallback uses the lightweight pypdf path.
- **nginx `/events` SSE route** — proxied in nginx config but **no `/events` endpoint exists** in the backend; ingestion progress is surfaced purely by 3s polling of `/documents`.
- **"Accurate/Pro" tier** — wired end-to-end but resolves to Flash under the current all-Flash `.env`.
- **Quota enforcement** — `Usage` rows are recorded; no kill-switch acts on them yet.
```
