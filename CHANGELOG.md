# Changelog

All notable changes per build phase. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Phase 3 (backend): Interviewer agent, text mode (2026-11-06)

#### Added
- `app/agents/interviewer/` (state, graph, nodes, prompts, tools): a LangGraph state machine with
  the nodes plan_interview, ask_question, evaluate_answer, decide_next, ask_follow_up and finish. The
  tools are `search_cv`, `search_rubric` and `score_answer`.
- Stateless turns: each request loads the JSON state from `interview_state`, advances exactly one
  turn and saves it. Questions go to `questions` (with `rubric_chunk_ids`) and answers to `answers`
  (scores and feedback). No new tables or migrations.
- Question mix chosen in code by `interview_type` (mixed, technical, behavioral) and difficulty. ONE
  strong-model call phrases all 6 questions. Rubric chunks and the 1/3/5 anchors are prefetched at
  planning time.
- ONE fast-model call per answer: SPEC 6.5 scores (string enums "1"-"5", quotes checked against the
  transcript), the follow-up decision signal and the follow-up phrasing. At most 1 follow-up per
  question.
- API: `POST /sessions/{id}/interview/start` (idempotent), `GET /sessions/{id}/interview` (with
  history) and `POST /sessions/{id}/interview/answer`. Errors: `not_analyzed`, `not_started`,
  `wrong_question`, `interview_completed`, `ai_unavailable` (503, nothing written, safe to retry) and
  `session_not_found`.
- Practice mode returns a one-line summary and a tip after each answer. Scores are never sent during
  the interview.
- 17 new tests (113 backend tests in total).

#### Dependencies
- `langgraph==1.2.20`, which pulls in `langchain-core` 1.7.6, langsmith, orjson, ormsgpack, xxhash
  and others: about 33 MB installed. Not the `langchain` meta-package. LangGraph is imported lazily,
  inside the interview service, because it takes about 2-3 s to import.

#### Verified live
- Full demo interview: 6 main questions plus 5 follow-ups, completed, then a 409 for answers after
  completion.
- Planning: 1.25K prompt + 0.4K completion tokens (gpt-oss-120b), 8.7 s including one 429 retry.
- Answer turns on Groq: 1.9-3.7 s end to end (~1.8K prompt + 0.3-0.7K completion tokens).
- Turns where back-to-back answers went over Groq's 8K TPM limit fell back to Gemini and took
  11-15 s.

#### Known risks
- Several users at once can exceed Groq's per-minute token limit and push turns into the slow
  Gemini fallback.
- Two concurrent answers to the same question could race. The last write wins, with no optimistic
  lock.
- Transitive dependencies of langgraph are not pinned.
- Report generation (Phase 5) is not built yet. `finish` only sets `report_pending`.

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
