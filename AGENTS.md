# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

Hotel AI Order Agent — an AI-powered ordering system for hotel maintenance scenarios. Backend is Python (FastAPI + LangGraph), frontend is Vue 3 (Vite).

### Services

| Service | Command | Port | Notes |
|---------|---------|------|-------|
| Backend (FastAPI) | `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` | 8000 | Requires `.env` with API keys for LLM calls |
| Frontend (Vite) | `cd frontend && npm run dev` | 5173 | Proxies `/api` → `localhost:8000` |

### Required secrets (environment variables)

The backend requires these API keys configured in `.env` to handle chat requests:

- `OPENAI_API_KEY` — OpenAI-compatible LLM API key
- `OPENAI_BASE_URL` — API base URL (leave blank for OpenAI default)
- `OPENAI_MODEL` — Model name (default: `gpt-4o-mini`)
- `QWEN_EMBEDDING_API_KEY` — DashScope Qwen embedding key (for product matching)

Without these keys, the `/health` endpoint and frontend UI still work, but `/api/chat` returns 500.

### Lint / Test / Build commands

See `README.md` for full details. Quick reference:

```bash
# Python compile check (lint equivalent — no ruff/flake8 configured)
uv run python -m compileall graph api schemas tools rag config app

# Pytest (currently no formal tests collected; test scripts exist in tests/)
uv run pytest

# Frontend build (includes vue-tsc type checking)
cd frontend && npm run build
```

### Non-obvious caveats

- Python version: the project pins `>=3.12,<3.13`. `uv sync` auto-downloads CPython 3.12 into `.venv`.
- The `.env` file uses `load_dotenv(".env", override=True)`, so `.env` values override system env vars.
- SQLite checkpoint DB is auto-created at `data/agent_memory.sqlite3` on first run.
- PostgreSQL/Redis/Qdrant are optional; keep `POSTGRES_ENABLED=false` in `.env` for local dev.
- No pre-commit hooks or lint-staged config exists in this repository.
