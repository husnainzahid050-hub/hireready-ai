# Changelog

All notable changes per build phase. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Security pass (2026-11-06)

#### Added
- Per-session quotas on LLM-consuming actions (migration `20261106000004_security.sql`:
  `session_usage` + atomic `consume_quota()`); uploads capped at 5 and fresh analyses at 3 per
  session, 429 `quota_exceeded`. **Apply the migration before deploying the backend.**
- Integration points for Phase 7: `RateLimiter` (no-op, or Upstash when `UPSTASH_*` is set) and a
  Turnstile verifier (no-op, or Cloudflare siteverify of `X-Turnstile-Token` when
  `TURNSTILE_SECRET_KEY` is set), wired into session create, upload and analyze.
- 4.5 MB request body limit; security headers and `Cache-Control: no-store` on every API response;
  `Cross-Origin-Opener-Policy: same-origin` on pages.
- `docs/SECURITY.md` (threat model, controls, pending items, SPEC 9 checklist).
- 65 security tests (`tests/test_security_api.py`, `tests/test_security_units.py`); 161 backend tests total.

#### Fixed
- Upload/analyze loop allowed unlimited LLM calls per session.
- PDF parser DoS: tighter pypdf limits, external `jbig2dec` disabled, any parser error is now a
  400 instead of a 500, DOCX entry cap, parsing runs off the event loop with a 15 s timeout.
- `wrap_untrusted` could be escaped with `</CV>` or `</cv >`; the insights prompt sent CV/JD-derived
  data unfenced; injected CV lines could be "verified" as evidence quotes.
- LLM fallback logs could contain model output (CV text); logs now mask emails and truncate long
  strings; `X-Request-ID` is sanitized.
- `ALLOWED_ORIGINS=*` is refused; `VERCEL_ENV=production` also hides the API docs.

### Phase 2: Intake and gap analysis (2026-11-06)

#### Added
- API: `POST /sessions` (consent required; `?demo=true` preloads the fictional "Ali Raza" CV and a
  Junior AI Engineer JD), `POST /sessions/{id}/documents` (multipart CV + JD),
  `POST /sessions/{id}/analyze` (SSE stream) and `GET /sessions/{id}/analysis`. Guest tokens are stored
  as SHA-256 hashes, and ownership is checked on every call.
- CV parsing: PDF/DOCX only, 2 MB and 5 pages max, MIME + magic-byte checks, a zip-bomb guard, and a
  clear error for scanned PDFs.
- LLM client: Groq strict JSON-schema output (`gpt-oss-20b` fast / `gpt-oss-120b` strong) with automatic
  fallback to Gemini (`gemini-3.5-flash`); token usage is logged.
- Gap analysis: parallel CV/JD extraction (JD cached by content hash), CV chunking + embedding, hybrid
  search per skill, evidence judging with verified quotes, a deterministic match score, strengths,
  likely questions adapted from the rubric KB, and a 7-day plan limited to curated URLs.
- Frontend: `/start` (dropzone, JD character counter, options, email opt-in, consent), a streamed
  `/session/[id]/analysis` page (progress, score gauge + formula, gap cards with quotes, strengths,
  questions, plan), and a "Try with a sample CV" button.
- 96 backend tests, plus a browser test of the full demo flow (desktop and mobile).

#### Changed vs. spec
- LLM calls use httpx directly (not LangChain) in Phase 2; LangGraph arrives with the agent in Phase 3.
- shadcn/ui is not added yet: plain Tailwind components for now, revisited in the Phase 6 polish.
- Turnstile and rate limits are in Phase 7 (as planned); until then the public demo has no abuse limits.

#### Verified live
- Demo analysis end to end: first event in ~0.5 s, complete in ~17-22 s, all on Groq. Re-opening a
  saved analysis takes under 1 s. No browser console errors.

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
- Groq models are `openai/gpt-oss-20b` (fast) and `openai/gpt-oss-120b` (strong): Llama models are not
  available on the account. Gemini text fallback: `gemini-2.5-flash`.

#### Verified live
- Migrations applied on Supabase; 157 knowledge chunks ingested; re-run is a no-op.
- Sample hybrid searches return the correct rubric section as the top result for all 5 queries.

#### Fixed
- Gemini embeddings: send top-level `taskType`/`outputDimensionality` (the API ignores
  `embedContentConfig` and returned 3072 dims).
- Backend deps declared in `pyproject.toml` (Vercel ignores `requirements.txt` when it exists).
- Ingestion waits out free-tier per-minute quotas (patient retry mode).

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
