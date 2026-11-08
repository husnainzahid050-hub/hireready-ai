# Changelog

All notable changes per build phase. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Phase 4: Voice (2026-11-08)

#### Added
- `POST /sessions/{id}/interview/answer` also accepts multipart `{question_id, audio}` (JSON text
  answers unchanged). Audio is validated (MIME + magic bytes, 3 MB, 120 s), transcribed with Groq
  Whisper (`GROQ_STT_MODEL`, `verbose_json` with segment + word timestamps) and never stored.
  Same quota/rate limit as text answers, charged after the cheap checks and before Whisper.
  503 `stt_unavailable` on provider failure; 422 `no_speech` / `audio_too_long` / `audio_unreadable`.
- `app/services/speech_metrics.py`: words per minute over speaking time, filler words (English +
  Urdu/Hinglish, context rules for "like", "you know", "kind of"/"sort of"), long pauses > 2 s.
  Stored in the `answers` columns; returned as optional `last_answer.speech_metrics`.
- Interview page: Voice / Text switch (default from the session's mode), lazy-loaded recorder
  (tap to start/stop, timer, 120 s auto-stop, level meter, mic released on stop/unmount), upload
  progress and "Transcribing..." state, retry upload without re-recording, mic denied/unsupported
  fallback to typing, questions read aloud with `speechSynthesis` + persisted mute + replay,
  practice-mode "How you sounded" card.

#### Tests
- Backend: +49 tests (`test_voice.py`, `test_speech_metrics.py`); 282 passed + 1 xfail in total.
- `frontend/e2e/voice.mock.py`: fake mic + mocked API (record -> upload -> next question, 503 retry,
  mute, mic denied, no MediaRecorder, 390x844 light/dark). Live smoke test: Whisper ~0.66 s per
  answer, stop -> next question 3.7 s / 8.8 s, 0% WER on a scripted answer with fillers kept.

### Integration & fixes (2026-11-06)

Merged the backend, frontend, security and QA work and fixed the open QA bugs. **Apply
`supabase/PENDING_MIGRATIONS.md` (migrations 04 and 05) before deploying this backend.**

#### Fixed
- **B3** Concurrent analyze calls ran the whole pipeline twice. Analyze now claims the session with
  `claim_analysis()` (migration `20261106000005_analysis_claim.sql`, one conditional UPDATE, atomic)
  before spending quota or LLM calls. A second caller streams a `waiting` status and then the first
  run's result (`analysis_interrupted` if that run dies, `analysis_in_progress` after 45 s). Claims
  are released when a run ends and expire after 120 s if a function is killed.
- **B8** The analysis has a 50 s budget (`analysis_timeout`, inside Vercel's 60 s), each LLM provider
  gets at most 25 s including retries, and a `slow` status is streamed after 15 s without progress or
  as soon as the LLM falls back to Gemini. The page shows an error with Try again if the stream ends
  without `done`/`error`.
- Interview security parity: `interview_start` / `interview_answer` quotas and rate limits, charged
  only for turns that call the LLM; the planning prompt now fences the JD-derived job and slot data.
- **B9** Internships, TA and similar student roles no longer count as experience for mid/senior roles.
- **B10** "Power BI or Tableau" stays one skill, satisfied by either option.
- **B12** JD over 20k chars gives `jd_too_long`; a malformed session id gives 404 `session_not_found`.
- **B13** A wrong or expired token shows the "another browser / expired" panel on the analysis page.
- **B14** A failed upload on `/start` reuses its session on retry (no orphan sessions).
- **B15** Insights and interview questions address the user as "you"; weak skills aren't called gaps.
- **B16** Index-based React keys on the analysis page.

#### Changed (simplification, no behaviour change)
- One set of test fakes (`backend/tests/fakes.py`) instead of copies in five test modules
  (-242 lines in tests); test modules no longer import from each other.
- One `session_not_found()` / `ai_unavailable()` error each; SSE formatting and error mapping in one
  helper (`app/core/sse.py` + `_sse_response`); `rubric_level()` replaces three copies;
  `submit_answer` uses a plain `gather` instead of manual task bookkeeping.

#### Tests
- 230 backend tests (+18: `tests/test_analysis_stream.py`, interview quota/rate-limit/fencing
  tests, seniority), migration smoke test covers the claim race with two connections, new mocked
  browser test `frontend/e2e/analysis.mock.py`.

#### Verified live (local backend + live Supabase, Groq, Gemini)
- Migrations 04/05 are not on the live database yet, so a local-only test harness stubbed the
  `consume_quota` / `claim_analysis` calls (production code unchanged; both are covered by the
  embedded-Postgres smoke test).
- Demo analysis: first event 0.7 s, done in 26.7 s. Groq returned 429 on the insights step, Gemini
  took over and the `slow` notice was streamed. Cached re-analyze 0.34 s.
- Interview: start 9.7 s, two answers 2.1 s and 1.8 s; the one-line answer got a follow-up.
- Browser: "Try with a sample CV" on `/start` streamed to a finished analysis with "Start interview".

#### Still open
- B4 (hidden white text counts as evidence), B6 (row-interleaved two-column PDFs), B11 (silent 30k
  truncation notice). pypdf's layout mode was tried for B6: it reversed Urdu text and interleaved a
  column-ordered Chrome PDF, so it is not a safe default.
- Two concurrent answers to the same interview question can still race (last write wins).

### Phase 3: Interviewer agent, text mode (2026-11-06)

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
- Frontend `/session/[id]/interview` (text mode): start screen with practice-mode switch, question
  caption card with interviewer status, "Question X of ~N" + follow-up badge, answer box (5,000-char
  counter, Ctrl/⌘+Enter), optimistic "thinking" state, transcript (collapsible on mobile),
  practice feedback, completion screen, resume after reload, and friendly 503/429/network/
  wrong-question handling that never loses the typed answer. The analysis page's "Start interview" CTA
  now links to it. Mocked-API browser test in `frontend/e2e/interview.mock.py`.

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
