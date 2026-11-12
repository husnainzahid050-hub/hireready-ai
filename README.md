# HireReady AI

> Paste the job. Upload your CV. Walk into the interview ready.

HireReady compares your CV against a specific job description, shows evidence-backed skill gaps,
runs a tailored voice or text mock interview with follow-up questions, and produces a scored report
with speech metrics and a 7-day prep plan.

**Status:** 🚧 Phase 8 (analysis, text + voice interview, UI, security hardening and an eval suite with published results in [evals/results.md](evals/results.md)). Before
deploying, apply the SQL in [supabase/PENDING_MIGRATIONS.md](supabase/PENDING_MIGRATIONS.md). See [SPEC.md](SPEC.md) for the full plan and
[CHANGELOG.md](CHANGELOG.md) for progress. The full README (demo, architecture, evals) lands in Phase 9.

## Stack

Next.js · TypeScript · Tailwind · FastAPI · Pydantic · LangGraph · Groq · Gemini · Supabase (pgvector) · Vercel

## Local setup

Requirements: Python 3.12, Node 24.

```bash
# Backend (terminal 1)
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements-dev.txt
cp ../.env.example .env       # fill in values as phases need them
uvicorn app.main:app --reload --port 8000

# Frontend (terminal 2)
cd frontend
npm install
npm run dev                   # http://localhost:3000 (proxies /api/* to :8000)
```

Checks: `ruff check . && mypy app && pytest` (backend), `npm run lint && npm run typecheck` (frontend).

### Database and knowledge base (Supabase)

1. Create a free Supabase project. In **Project Settings → API keys**, copy the project URL and a
   **secret** key (`sb_secret_...`) into `backend/.env` as `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`.
2. Open **SQL Editor** and run the files in `supabase/migrations/` in filename order.
3. Add `GEMINI_API_KEY` (Google AI Studio) to `backend/.env`, then from `backend/`:

```bash
python -m scripts.ingest_knowledge --dry-run   # validate files, no network
python -m scripts.ingest_knowledge             # embed + upsert (safe to re-run)
python -m scripts.search_demo                  # sample hybrid-search queries
```

Migrations can also be tested locally without Supabase:
`pip install -r supabase/tests/requirements.txt && python supabase/tests/test_migrations.py`.

## Repository layout

```
backend/    FastAPI app (Vercel project, root dir = backend)
frontend/   Next.js app (Vercel project, root dir = frontend)
backend/knowledge/   curated rubric knowledge base (one markdown file per competency)
supabase/   SQL migrations + local migration smoke test
docs/       LEARNING.md (concepts per phase), architecture, security
```
