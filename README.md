# Contract Analyzer

Analyze large legal contracts (100–2000 pages). Upload a document, ask questions, and get
answers **with verified citations** (page / section / bounding-box). Built for selective
spend: cheap on easy questions, escalate only the hard/high-stakes ones.

- **Design:** [ARCHITECTURE.md](ARCHITECTURE.md)
- **Stack & build log:** [STACK.md](STACK.md)
- **Local dev (no Docker):** [LOCAL_DEV.md](LOCAL_DEV.md)

## Run locally (no Docker)

See [LOCAL_DEV.md](LOCAL_DEV.md) — runs the stack as native processes (Postgres+pgvector,
Redis, uvicorn, arq, Vite). Local uses Postgres built-in full-text (`FTS_BACKEND=tsvector`)
instead of ParadeDB `pg_search`.

## Run with Docker (VPS / production)

```bash
cp .env.example .env        # fill in GEMINI_API_KEY etc. (keep FTS_BACKEND=pg_search)
docker compose up --build
docker compose exec backend alembic upgrade head   # first run: migrations
```

- API:        http://localhost:8000  (docs at `/docs`)
- Frontend:   http://localhost:5173

## Services

| Service | Port | What |
|---|---|---|
| backend  | 8000 | FastAPI REST + SSE |
| worker   | —    | arq ingestion (parse/chunk/embed) |
| frontend | 5173 | React + Vite |
| db       | 5432 | Postgres (ParadeDB: pgvector + pg_search) |
| redis    | 6379 | arq broker |

Raw files are stored on a local Docker volume (`filedata` → `/data/files`), not S3.
