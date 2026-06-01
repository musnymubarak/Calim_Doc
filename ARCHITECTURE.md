# Contract Analyzer — Architecture

A system for analyzing large legal contracts (100–2000 pages, PDF/DOCX). Users upload a
document, ask questions, and get answers **with verified citations** (page / section /
bounding-box). Later extension: risk-analysis reports.

**Design driver:** citation fidelity is the spine, and cost + accuracy are reconciled by
**selective spend** — a cheap baseline on every query, escalating only the ~15–25% that
cheap *structural* signals flag as hard.

---

## 1. Stack

| Layer | Choice | Notes |
|---|---|---|
| API | **FastAPI** (Python) | async; serves REST + SSE for ingest progress |
| Frontend | **React** (Vite) + PDF.js | split view: document viewer + chat |
| DB | **PostgreSQL** + **pgvector** | vectors live in Postgres; no separate vector DB |
| Full-text | **ParadeDB `pg_search`** | real BM25 (Postgres `ts_rank` is not enough) |
| Worker | **arq** + Redis | async ingestion (parse/chunk/embed) |
| File storage | **Local filesystem** (VPS volume) | raw uploaded files; abstracted behind a storage interface |
| Parsing | **Docling** | PDF/DOCX → structured; OCR fallback for scans |
| LLM | **Gemini** (current 3.x tier) | Flash-first; Pro on escalation |
| Embeddings | **gemini-embedding-001**, 768-dim (MRL) | stored as `halfvec` |
| Reranker | **self-hosted cross-encoder** | validated on labeled contract queries |

> Model IDs are not hardcoded — they live in a **model registry** (config/DB). 2.5 retired
> 2026-03-03; bind to the live 3.x tier.

---

## 2. System overview

```
┌─────────────┐   upload    ┌──────────────┐  enqueue   ┌─────────────┐
│   React     │ ──────────► │   FastAPI    │ ─────────► │   Worker    │
│ viewer+chat │ ◄────────── │     API      │ ◄── status │   (arq)     │
└─────────────┘   SSE/ask   └──────┬───────┘            └──────┬──────┘
                                   │                           │
                ┌──────────────────┴───────────────────────────┴────────┐
                │  PostgreSQL + pgvector + pg_search                     │
                │  users · documents · chunks · embeddings ·             │
                │  defined_terms · cross_ref_edges · governance_records ·│
                │  conversations · messages · answer_cache · usage       │
                └──────────────────┬───────────────────────────┬────────┘
                                   │                           │
                            ┌──────┴──────┐            ┌────────┴────────┐
                            │ Gemini API  │            │  Local FS       │
                            │ embed/gen/  │            │  (VPS volume:   │
                            │ cache       │            │   raw files)    │
                            └─────────────┘            └─────────────────┘
   (everything except the Gemini API runs on a single VPS)
```

---

## 3. Data model

```sql
users(id, email, created_at)

documents(
  id, user_id → users,
  filename, mime_type, page_count,
  storage_uri,           -- local FS path on the VPS volume (interface allows S3 later)
  content_hash,          -- SHA-256 of blob (dedup on upload)
  text_hash,             -- normalized-text hash (dedup re-scans)
  doc_version,           -- version label; bumped on re-upload
  doc_role,              -- base | amendment | restatement | schedule | exhibit
  effective_date,
  amendment_order int,
  status,                -- uploaded|parsing|ocr|chunking|embedding|ready|failed
  error_msg,
  strategy,              -- 'rag' | 'cached_whole'  (by token size vs 200K tier)
  gemini_cache_name, cache_expires_at,   -- only if cached_whole (lazy, short TTL)
  created_at
)

chunks(
  id, document_id → documents,
  ordinal,
  content text,
  page_start, page_end,
  bbox jsonb,            -- [{page,x0,y0,x1,y1}] for highlight overlay
  section_path text,     -- "4.2 > Indemnification"
  char_start, char_end,
  is_table bool,         -- tables kept atomic (caption + headers)
  list_group text,       -- (a)-(z)/(i)-(x) groups never split
  token_count int
)

embeddings(
  chunk_id → chunks (pk),
  embedding halfvec(768),
  embedding_model text, dim int, chunking_version int   -- versioned → incremental re-embeds
)
-- CREATE INDEX ON embeddings USING hnsw (embedding halfvec_cosine_ops);
-- full-text (BM25) index on chunks.content via pg_search

-- ── ingest-time correctness structures (compute once) ───────────────
defined_terms(
  id, document_id → documents,
  term text, definition text,
  source_chunk_id → chunks, depth int      -- nested-term resolution, capped
)
cross_ref_edges(
  id, document_id → documents,
  from_chunk_id → chunks,
  target_ref text,                          -- "Section 12.3", "Schedule B"
  target_chunk_id → chunks NULL,            -- resolved target if found
  kind text,                                -- explicit | relative | incorporation
  confidence real, resolved bool            -- relative refs flagged, not trusted
)
governance_records(
  id, document_id → documents,
  kind text,                                -- precedence | MFN | conflict | renewal
  chunk_id → chunks, detail text
)

-- ── conversation + answers ──────────────────────────────────────────
conversations(id, document_id → documents, user_id, created_at)

messages(
  id, conversation_id → conversations,
  role,                                     -- user | assistant
  content text,
  citations jsonb,                          -- [{chunk_id,page,section,cited_span,polarity,verified}]
  exceptions jsonb,                         -- carve-outs surfaced
  answerable bool, missing_context jsonb,
  confidence text,
  model text, tier text,                    -- which model/tier produced it
  escalated bool, escalation_reason text,
  token_usage jsonb,                        -- {input,output,cached}
  created_at
)

answer_cache(
  id, document_id → documents,
  doc_version_hash text,                    -- invalidates on re-upload
  normalized_question text,                 -- exact-tier key
  question_embedding halfvec(768),          -- semantic-tier (gated ≥0.95)
  answer text, citations jsonb,
  tier text,                                -- 'exact' | 'escalated'
  verified bool,                            -- NEVER cache unverified outputs
  created_at
)

usage(id, user_id, document_id, kind, input_tokens, output_tokens, cached_tokens, cost_est, created_at)
```

---

## 4. Ingestion pipeline (worker, async)

Each stage updates `documents.status` → React shows progress via SSE.

```
1. RECEIVE   → store raw blob; SHA-256 content_hash + normalized text_hash
                ├─ hash match (same user / ACL) → link to existing chunks, SKIP rest
2. PARSE     → Docling: PDF/DOCX → structured (text + page + bbox + headings)
                ├─ no text layer → OCR fallback (detect, don't OCR blindly)
3. CHUNK     → ~500-800 tokens, ~15% overlap, structure-aware splits
                ├─ tables = ONE atomic chunk (caption + column headers)
                ├─ NEVER split (a)-(z) / (i)-(x) lists
                └─ carry page/bbox/section_path/char offsets  ← provenance, never dropped
4. STRUCTURE → build defined_terms, cross_ref_edges (+flag relative refs),
                governance_records, version/precedence tags
                (one cheap batched Flash-Lite classify per section ≈ pennies/doc)
5. EMBED     → batch via Batch API (50% off), 768-dim → halfvec
6. PERSIST   → chunks + embeddings + structures; status=ready
   (any failure → status=failed + error_msg, surfaced in UI)
```

Ingestion uses the **Batch API** (not the synchronous endpoint) — it's already async, and
embeddings + reports are the most predictable cost line.

---

## 5. Query flow — the escalation ladder

### (a) Always-on cheap baseline — every query, ~$0.002–0.004
```
Cache check (exact: doc_version_hash + normalized-Q)         ~$0.0000045
  └─ verified hit → SERVE
Hybrid retrieve: pgvector(dense) + pg_search(BM25), RRF k=60, 40-60 candidates
Self-hosted cross-encoder rerank → top 8-12
Gated injection (cap 2-3, dedup):
  • definition  → only if the defined Term appears in a retrieved clause
  • cross-ref   → only on explicit modifier + high edge confidence
  • precedence  → if clauses span two instruments/tiers
  • amendment   → pass BOTH versions + dated supersession note
Generate: Gemini Flash, thinking OFF, ≤8-12K ctx, structured JSON,
  grounding+abstention rules in CACHED system prefix
Run free gates + compute escalation signals
```

### Always-on correctness gates (free, deterministic — run on 100%)
1. **Structured per-claim output:** `{claim, cited_span(char offsets), chunk_id, page,
   section, polarity, exceptions[], missing_context[], answerable}`.
2. **Char-offset span verification** — cited quote must offset-match the chunk (catches
   fabricated ellipses, not just substring presence).
3. **Carve-out sufficiency scan** — if a cited clause contains `except / unless / provided
   that / notwithstanding / subject to` (same clause, not boilerplate) and `exceptions[]`
   is empty → fail/escalate.
4. **Abstention is first-class** — `answerable=false` + `missing_context[]` when a
   referenced clause/definition/version isn't in context. Distinguish *retrieval missed it*
   (→ re-retrieve) from *contract is silent* (→ abstain).

### (b) Escalation triggers (all near-free to compute)
Citation/span gate fails · carve-out scan trips · `answerable=false` (after one cheap
re-retrieve) · weak retrieval (flat RRF score-gap, BM25-vs-dense disagreement — use
*relative* gap, not an absolute cosine cutoff) · a guard activated (cross-ref / two
versions / precedence) · query shape (deontic "can/must", names amounts/dates/caps,
multi-section, multi-doc) · **high-stakes clause type** (indemnity, liability cap,
termination, IP, change-of-control, governing law, auto-renewal → route **up front**) ·
user thumbs-down.

> **Never** gate spend on self-reported confidence (~0.63 AUROC) or embedding-cosine
> grounding (88–100% FPR).

### (c) Escalated path — cheapest fix first, ~$0.02–0.05
```
1. RETRIEVAL FIX   widen K=30-50, accurate rerank, HyDE/rewrite ONLY for vague queries
                   (never for exact section/number lookups), re-run Flash thinking ~1-2K   ~$0.006-0.008
2. REASONING FIX   raise thinking budget → Gemini Pro single-pass (≤200K tier)             ~$0.02-0.03
3. VERIFY          ONE independent Flash critic pass (NOT the generator):                  +~$0.002
                   "every claim has a verbatim span? all carve-outs reflected?
                    latest-effective version used? any cross-ref ignored?"
                   hard negation/precedence → HUMAN review, don't auto-clear
```
Persist every **verified** escalated answer → `answer_cache(tier='escalated')`. Repeats
serve Pro-grade for ~$0.0000045; re-upload changes the hash → auto-invalidates.

> Drop N-sample self-consistency as a default rung (re-agrees on the same incomplete answer
> at N× cost). Reserve N≤3 only for high-stakes cases still low-agreement after Pro+critic;
> on disagreement, return "ambiguous" rather than a forced answer.

---

## 6. Cost controls (shared key → operator eats 100%)

- **Hard context cap** (~8–12K tokens) on the assembled prompt; cap K + expansion; dedup overlap.
- **Two-tier answer cache** (exact always-on; semantic gated ≥0.95 + negation/entity guard + re-verify).
- **Batch API** for ingestion + reports (flat 50% off).
- **Content-hash dedup** on upload (per-user reference rows + ACL — never merge two users' docs).
- **`max_output_tokens`** caps; thinking bills as output.
- **Per-user quotas + global daily spend kill-switch** (convert usage tracking into hard caps).
- **768-dim MRL + halfvec** (~4× less pgvector RAM; also dodges the 2000-dim HNSW cap).
- **Lazy, short-TTL `cached_whole`** for small docs only (create on 1st–2nd question, 15–30 min TTL).

**Blended cost:** ~$0.005–0.008/query — ~1.25–2× all-Flash, **4–6× cheaper than all-Pro**.
🔑 If escalation rate > 25%, the bug is parsing/chunking, not the model tier.

---

## 7. Model strategy

- **Registry-driven** model list (no hardcoded IDs).
- **Auto-routing is the default** (Flash-first, escalate per §5b).
- End-user override exposed as **tier presets** ("Fast / Balanced / Most accurate"), not raw
  model IDs, behind an Advanced toggle — gated by per-user quotas.
- `messages.model` + `messages.tier` recorded for cost attribution, reproducibility, and
  cache keying (cache is model-sensitive).

---

## 8. Evaluation harness (build alongside, not after)

Before trusting any signal to spend money:
- Build a **small human-labeled contract-QA eval set** (questions + correct clause spans).
- Measure each escalation signal's **AUROC/ECE**, and the reranker's **end-to-end
  citation-correctness** (not NDCG — NDCG correlates weakly with answer correctness).
- In prod, track **context-recall** and **false-abstention rate**, not just faithfulness
  (documented legal-RAG failure: 0.91 faithfulness but 0.62 recall — confidently answered
  from the wrong clauses).

---

## 9. Build order (highest accuracy-per-dollar first)

1. **Parsing discipline + ingest guards** — tables atomic, lists intact, defined-term map,
   cross-ref graph, version tags. *(The spine. Most subtle-wrong answers originate here.)*
2. **Hybrid retrieval** — pgvector + pg_search BM25, RRF + gated injection.
3. **Self-hosted reranker** — validate on ~200 labeled queries before trusting.
4. **Free gates** — span-offset verify, carve-out scan, abstention.
5. **Cheap routing signals → escalation.**
6. **Thinking budget, then Pro** — model upgrades LAST; they fix reasoning, not retrieval/parsing/scope.
7. **One Flash critic pass** on escalation.

Cross-cutting from day one: provenance-preserving chunker, citation-verification gate,
per-user usage + quotas, the eval harness.

---

## 10. Repo layout

```
backend/
  app/
    api/            # routes: upload, documents, chat, conversations
    workers/        # arq tasks: parse, structure, chunk, embed
    services/
      ingestion/    # docling, ocr, provenance chunker, structure extractors
      retrieval/    # hybrid search, RRF, rerank, gated injection
      gemini/       # model registry, caching, structured-output schemas
      answers/      # escalation ladder, gates, critic pass
      citations/    # span-offset verification gate
      eval/         # labeled set + metrics
    models/         # SQLAlchemy + pgvector/halfvec
    db/             # alembic migrations
  pyproject.toml
frontend/
  src/features/{upload,viewer,chat}/
docker-compose.yml  # postgres(+pgvector,pg_search), redis, backend, worker, frontend
```

---

## 11. Deployment (single VPS)

Everything except the Gemini API runs on one VPS (docker-compose). Raw files live on a
local volume, not object storage.

- **Storage abstraction.** Code talks to a `Storage` interface (`save / open / delete`),
  with a `LocalFSStorage` implementation. Keeps the door open to swap in S3 later without
  touching call sites — but no S3 dependency now.
- **File path layout.** Store under a per-user, content-addressed path
  (`/data/files/{user_id}/{content_hash}.{ext}`); `documents.storage_uri` holds it. The
  content-hash layout makes dedup and idempotent re-upload trivial.
- **Disk planning — the main new risk.** Large contracts accumulate (a 2000-page scanned
  PDF can be 100s of MB). The DB, pgvector indexes, raw files, and Postgres WAL all share
  the same disk. Monitor free space; alert well before full (a full disk corrupts Postgres).
  Content-hash dedup and tiering/expiring cold raw files help. Put `/data` on a volume you
  can resize.
- **Backups.** No S3 durability means backups are on you: scheduled `pg_dump` (or
  volume snapshots) **and** the raw-files directory. The DB alone is not enough — you'd lose
  the source documents. Store backups off the VPS.
- **Single point of failure.** One VPS = no redundancy; fine for launch scale, but the disk
  and the box are now the durability boundary. Worth a note for when you grow.
- **Secrets.** The shared Gemini API key lives in env/secret on the VPS — not in the repo.

