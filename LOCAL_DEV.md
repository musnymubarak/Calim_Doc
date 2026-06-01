# Local development (no Docker)

Run the whole stack as native processes. The only architectural change vs. the Docker setup
is the **full-text backend**: locally we use Postgres's built-in `tsvector`/`ts_rank`
(`FTS_BACKEND=tsvector`) instead of ParadeDB `pg_search`, because `pg_search` has no native
install path (it ships as the ParadeDB Docker image). Retrieval quality is a bit lower locally;
production on the VPS keeps `pg_search`. Everything else (pgvector, Gemini, arq, FastAPI, React)
is identical.

You need five things running: **Postgres (+pgvector)**, **Redis**, the **FastAPI API**, the
**arq worker**, and the **Vite frontend**.

---

## Recommended: WSL2 (Ubuntu) — smoothest on Windows

Native Windows builds of pgvector and Redis are awkward; WSL2 makes them one-liners and is not
Docker.

```bash
# In an Ubuntu (WSL2) shell:
sudo apt update
sudo apt install -y postgresql postgresql-16-pgvector redis-server python3.12 python3.12-venv nodejs npm

# Start services
sudo service postgresql start
sudo service redis-server start

# Create DB + user
sudo -u postgres psql -c "CREATE USER contract WITH PASSWORD 'contract' SUPERUSER;"
sudo -u postgres psql -c "CREATE DATABASE contract OWNER contract;"
```

`postgresql-16-pgvector` installs the `vector` extension (the migration runs `CREATE EXTENSION
vector`). No `pg_search` needed because we set `FTS_BACKEND=tsvector`.

---

## Alternative: native Windows

- **PostgreSQL 16** — install via the EDB installer.
- **pgvector** — the fiddly part on Windows: build with MSVC per the
  [pgvector Windows instructions](https://github.com/pgvector/pgvector#windows) (needs Visual
  Studio Build Tools + `nmake`), or use a community prebuilt binary matching your PG version.
- **Redis** — Redis has no official Windows build; use **[Memurai](https://www.memurai.com/)**
  (Redis-compatible Windows service) or run `redis-server` inside WSL2.
- Then create the `contract` DB/user with pgAdmin or `psql`.

---

## Backend

```powershell
# From the repo root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".\backend"        # installs FastAPI, SQLAlchemy, arq, docling, google-genai, …
```

> Docling pulls sizable model weights on first parse — expect a slow first ingestion.

Create `.env` in the repo root (the backend reads it):

```ini
DATABASE_URL=postgresql+asyncpg://contract:contract@localhost:5432/contract
REDIS_URL=redis://localhost:6379/0
GEMINI_API_KEY=your-key-here
FTS_BACKEND=tsvector
FILE_STORAGE_DIR=./data/files
GEMINI_MODEL_FAST=gemini-flash-latest
GEMINI_MODEL_ACCURATE=gemini-pro-latest
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIM=768
```

Apply migrations, then run the API and worker in **two terminals** (both with the venv active,
from the `backend/` dir):

```powershell
cd backend
alembic upgrade head                                   # creates extensions, tables, indexes

uvicorn app.main:app --reload --port 8000              # terminal 1: API  → http://localhost:8000/docs
arq app.workers.main.WorkerSettings                    # terminal 2: ingestion worker
```

---

## Frontend

```powershell
cd frontend
npm install
npm run dev        # http://localhost:5173  (proxies API at VITE_API_URL, default http://localhost:8000)
```

---

## Smoke test

1. Open http://localhost:5173, upload a small PDF/DOCX.
2. Watch the worker terminal — status should walk `parsing → chunking → structuring →
   embedding → ready` (needs a valid `GEMINI_API_KEY`).
3. Select the document, ask a question → answer with citations.

## Gotchas

- **`FILE_STORAGE_DIR`** — on Windows set an absolute path or a repo-relative `./data/files`
  (the Docker default `/data/files` won't exist locally). It's auto-created on first upload.
- **`tsvector` vs `pg_search`** — local search is "good enough"; don't benchmark retrieval
  quality here, benchmark it on the VPS with `pg_search`.
- **No `GEMINI_API_KEY`** — ingestion fails at the `embedding` stage and the document goes
  `failed`; the parse/chunk/structure stages still run.
- **Switching `FTS_BACKEND` after migrating** — the FTS index is created by the migration to
  match the backend; if you change it later, create the matching index manually (or re-migrate).
