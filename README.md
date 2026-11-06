# HireReady AI

> Paste the job. Upload your CV. Walk into the interview ready.

HireReady compares your CV against a specific job description, shows evidence-backed skill gaps,
runs a tailored voice or text mock interview with follow-up questions, and produces a scored report
with speech metrics and a 7-day prep plan.

**Status:** 🚧 Phase 0 (scaffolding). See [SPEC.md](SPEC.md) for the full plan and
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

## Repository layout

```
backend/    FastAPI app (Vercel project, root dir = backend)
frontend/   Next.js app (Vercel project, root dir = frontend)
docs/       LEARNING.md (concepts per phase), architecture, security
```
