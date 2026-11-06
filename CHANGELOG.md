# Changelog

All notable changes per build phase. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Phase 1: Database and knowledge base (2026-11-06)

#### Added
- Supabase migrations: all spec tables (sessions, documents, doc_chunks, knowledge_chunks,
  gap_analyses, questions, answers, interview_state, reports, reminders), enums, length checks,
  cascade deletes, HNSW (cosine) + GIN indexes.
- Security: RLS enabled on every table with no policies, all grants revoked from `anon` and
  `authenticated` (including default privileges), `hybrid_search` executable only by `service_role`.
- `hybrid_search(query_embedding, query_text, match_count, filter)`: vector + full-text fused with
  Reciprocal Rank Fusion; filters for the rubric KB (competency, level) or one session's CV.
- Migration smoke test on embedded Postgres + pgvector (`supabase/tests/test_migrations.py`), run in CI.
- Knowledge base: 14 competency files (157 chunks) with what's evaluated, junior/mid question banks
  (strong answer, weak answers, red flags), 1/3/5 scoring anchors, and verified resource URLs.
- Services: shared httpx client with retry/backoff, minimal Supabase REST client, Gemini embeddings
  (768-d, L2-normalized, batched), heading-aware markdown chunker, hybrid `Retriever`
  (`search_rubric`, `search_cv`), idempotent knowledge ingestion.
- Scripts: `python -m scripts.ingest_knowledge [--dry-run]`, `python -m scripts.search_demo`.
- CI: knowledge-base validation step, database job; manual `ingest-knowledge` workflow.
- Tests: 57 backend tests (all external calls mocked).

#### Changed vs. spec
- Supabase is called over REST with httpx instead of the `supabase` SDK (smaller bundle).
- `pgcrypto` not enabled: `gen_random_uuid()` is built into Postgres 13+.
- Added `sessions.is_demo` and `reminders.unsubscribe_token` (needed for demo mode and Phase 7).

### Phase 0: Scaffolding (2026-11-06)

#### Added
- Monorepo with `frontend/` (Next.js 16.4, React 19, TypeScript strict, Tailwind v4) and
  `backend/` (FastAPI 0.162, Pydantic 2.14, Python 3.12).
- Backend: env-driven `Settings` (secrets as `SecretStr`), structured JSON logging with
  request IDs, a consistent `{"error": {"code", "message"}}` envelope that never leaks stack traces,
  and `GET /api/v1/health`.
- Backend tests (9) for health, error envelope, and config; ruff + mypy (strict) clean.
- Frontend: `/api/*` rewrite to the backend (`BACKEND_URL`, server-side only), baseline security
  headers (CSP, HSTS, nosniff, Referrer-Policy, Permissions-Policy `microphone=(self)`,
  frame-ancestors none), and a placeholder home page that calls the health endpoint.
- Prettier + ESLint + `next typegen && tsc` typecheck.
- GitHub Actions CI: lint, format, typecheck, tests, build, `pip-audit`, `npm audit`.
- `.env.example`, `SPEC.md`, `docs/LEARNING.md`.

#### Changed vs. spec
- No `backend/api/index.py`: Vercel now auto-detects the FastAPI `app` in `backend/app/main.py`.
