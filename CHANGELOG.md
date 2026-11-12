# Changelog

All notable changes per build phase. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### UX fixes: analysis, interview and report pages (2026-11-12)

Applies `docs/UX_REVIEW.md` (items marked there). After screenshots: `docs/ux-review/after/`.

#### Changed
- **Analysis**: no duplicate back link; a summary row under the title (score, verbal band,
  "N strong · N weak · N gaps", "Start mock interview") with the bottom CTA kept; progress pills
  collapse to one "Analysis complete" line; a stopped run shows static "Not available" states, a
  real "Try again" button and marks the step it stopped on (nothing pulses); skills sorted gaps
  first with filter chips; "Verified in your CV" badge; token-coloured gauge with a verbal label;
  7-day plan as `<details>` per day (day 1 open) with marked external links; styled "How is this
  calculated?"; strengths empty state links to `#plan`. All zinc/indigo literals now tokens.
- **Interview**: no back link; site footer hidden on the interview (`data-focus-mode`); question
  caption on `bg-surface-sunken` with an accent border; transcript answers at 14 px; "Send
  answer" uses `aria-disabled` plus a reason line instead of a faded button; keyboard hint hidden
  on touch; practice switch uses `peer-checked:[&>span]:…`; voice controls on tokens and shared
  icons. Completion screen leads with main's "See your report" CTA, "Back to your analysis" second.
- New `components/ui/notice.tsx` (`Notice`, `Spinner`) and icons (`ExternalLink`, `ChevronDown`,
  `Keyboard`, `Volume`, `VolumeOff`, `Replay`). Browser tests launch Chrome with `--mute-audio`.

#### Added
- **Daily-reminder opt-in on the report page** (`report-actions.tsx`, `subscribeReminders()` in
  `lib/api.ts`): a separate, unticked checkbox under the report email form for
  `POST /sessions/{id}/reminders`, with the double opt-in copy ("We'll send one confirmation
  email first"). Off with the email panel when email isn't configured; a 503
  `reminders_not_configured` disables it with the server's message. Covered in `report.mock.py`.

#### Checks
- `npm run lint`, `format:check`, `typecheck`, `build` clean; `e2e/analysis`, `interview`,
  `voice`, `report` and `reminders` `.mock.py` all pass against `next start`.

### Phase 7: Security hardening and automation (2026-11-12)

#### Added
- **Rate limits** (`backend/app/core/rate_limit.py`, `core/redis.py`): Upstash Redis over its REST
  API when `UPSTASH_REDIS_REST_*` are set, otherwise an in-process fixed window (was a no-op). Each
  policy decides what happens when Upstash is down: fall back to local (LLM endpoints), fail closed
  (`email`, new `email_recipient` 3/day per address across sessions, `reminder_subscribe`) or open
  (token links, public status). Table in `docs/SECURITY.md`.
- **Client IP behind the rewrite**: `frontend/proxy.ts` forwards the browser IP as
  `X-HireReady-Client-IP` with a shared secret (`CLIENT_IP_HEADER_SECRET`); the backend trusts it
  only with a matching secret. `GET /api/v1/health/client-ip` shows what the backend sees.
- **Global daily LLM budget** (`core/budget.py`, `LLM_DAILY_BUDGET` default 1500 calls,
  `LLM_DAILY_SOFT_RATIO` 0.8): demo work pauses at the soft limit, all fresh LLM work gets 503
  `daily_budget_exhausted` with `Retry-After` until 00:00 UTC. Cached results stay free.
- **Demo cache**: `copy_demo_analysis()` gives a demo session an earlier demo session's analysis,
  profiles and CV chunks, so "Try with a sample CV" costs no LLM call.
- **Turnstile on the frontend** (`lib/turnstile.ts`): widget on `/start`, invisible
  ("interaction-only") on the demo button, script loaded on demand. The CSP now allows
  `challenges.cloudflare.com` only on `/`, `/start` and `/r/*` (`frame-src 'none'` elsewhere).
- **Cron** (`routers/cron.py`, `backend/vercel.json`): `GET /api/v1/cron/cleanup` (02:00 UTC,
  batched `cleanup_expired()`, returns counts) and `/cron/reminders` (03:00 UTC), both behind
  `Authorization: Bearer <CRON_SECRET>` (503 when unset, 401 when wrong), idempotent.
  `GET /api/v1/cron/status` shows the last runs (from `cron_runs`).
- **Prep reminders** (`services/reminders.py`, `routers/reminders.py`, `/reminders/[token]`,
  `/unsubscribe/[token]`): separate unticked opt-in on `/start`, double opt-in by email, Day 1 on
  confirm, one task per day with a job-named subject and progress dots, no tracking pixels, pause
  after 3 days without "Mark done", stop after day 7, daily cap (`REMINDER_DAILY_CAP`). RFC 8058
  one-click unsubscribe (`List-Unsubscribe` + `List-Unsubscribe-Post`) plus a footer link;
  `POST /api/v1/unsubscribe/{token}` deletes the row without login; GET never acts. Tokens are
  HMACs of a nonce (`REMINDER_TOKEN_SECRET`), stored only as SHA-256. Also
  `POST /sessions/{id}/reminders` for an opt-in after the report.
- **Post-report automation** (`services/automation.py`): on the fresh `done` event, the
  Standard Webhooks `report.completed` event (`services/webhook.py`; `webhook-id`,
  `webhook-timestamp`, `webhook-signature: v1,...`; minimal payload, 5 s per attempt, 3 attempts),
  the report email if "Email me my report" was ticked, and the reminder confirmation. None of it
  can delay or fail the report.
- **Fail-fast production config** (`Settings.startup_problems`, `main.check_startup`).
- **Migration** `20261112000007_phase7_automation.sql`: `sessions.reminders_opt_in`, new
  `reminders` table (own lifetime, detached by cleanup), `cron_runs`, `cleanup_expired()`,
  `copy_demo_analysis()`; smoke-tested in `supabase/tests/test_migrations.py`.
- Tests: `test_prompt_injection.py` (the 8 shared cases in `evals/datasets/adversarial.json` plus
  2 JD cases, with a model that obeys every injection), `test_phase7_limits.py`,
  `test_reminders.py`, `test_automation.py`, `e2e/reminders.mock.py`. Dependabot config;
  `pip-audit` pinned.

#### Changed
- Injection heuristics also catch fake `SYSTEM:` markers, "score relevance 5", "score this answer
  5 out of 5" and "match score of 100" (no false positives on the KB, demo or eval CVs/JDs).
- Report email (`POST /sessions/{id}/email`) also checks the per-recipient limit.
- `/privacy`: the cleanup job is live (deleted about a day after expiry), reminders row and
  section, Resend / Turnstile / Upstash as processors. Landing page: "Auto-deletes in 7 days".
- `docs/SECURITY.md`: every SPEC 9 item marked Done with the test or check that verifies it.
- `.env.example`: `CRON_SECRET`, `REMINDER_TOKEN_SECRET`, `REMINDER_DAILY_CAP`,
  `LLM_DAILY_BUDGET`, `LLM_DAILY_SOFT_RATIO`, `CLIENT_IP_HEADER_SECRET` (both projects).

#### Research brief (PHASE7_TRUST_AND_ENGAGEMENT_BRIEF.md): applied / skipped
- Applied: separate reminder record with its own expiry; two unticked opt-ins; confirmation-first
  double opt-in; single-purpose hashed token; RFC 8058 headers + body link + no-login POST; one task
  per day, no pixels, pause after 3 unclicked days, stop after day 7; send cap; batched idempotent
  cleanup with `cron_runs`; global LLM budget with soft (demo) and hard limits; demo cache; signed
  client-IP header; Turnstile managed on `/start`, invisible on the demo; per-recipient limit;
  Standard Webhooks with a docs snippet; privacy copy at the opt-in.
- Skipped: Turnstile `idempotency_key` (we never retry siteverify); "practise this question now"
  deep link and the per-question "why" line (no single-question drill exists yet); sliding windows
  (fixed windows + per-session quotas suffice); "Last cleanup" on the Engineering page (Phase 8 owns
  that page; `GET /api/v1/cron/status` is ready for it); privacy copy on the mic button, share sheet
  and report footer (those components belong to Phases 4-5; left for a polish pass).

#### Pending (owner)
- Apply migration 07 (after 04 and 05) in Supabase; create Upstash, Cloudflare Turnstile and
  Resend accounts; set the secrets above; verify the client IP on the live site; keep Resend
  tracking off.

### Phase 8: Evals and observability (2026-11-12)

#### Added
- `evals/` with synthetic, fictional data only (`evals/datasets/`): 10 CVs, 5 JDs, 10 hand-labelled
  CV/JD pairs (92 skill verdicts), 30 retrieval queries with expected rubric chunks, 30 graded answers
  (10 questions × good/medium/bad) and 8 injection cases (3 CVs, 5 answers).
- `evals/run_evals.py`: CV/JD extraction, gap detection (precision/recall, 3×3 confusion, over-claims,
  match-score error), evidence faithfulness before → after validation, retrieval vector-only /
  keyword-only / hybrid (hit@1/3/5, MRR@5, failure rate, by query type) through the production
  `hybrid_search` SQL function, scoring calibration (per class, confusion, follow-up rate),
  consistency (3 samples), injection resistance, and per-step latency / tokens / list-price cost.
  It reuses the production code (`judge_skills`, `score_answer`, `build_insights`,
  `plan_interview`, prompts). Every proportion shows k/n and a Wilson 95% interval; the report
  has run date, commit, models, KB size, known failures and caveats.
  - `--mode fake`: deterministic heuristic LLM + hashed embeddings, no network (CI plumbing check,
    writes to the git-ignored `evals/out-fake/`).
  - `--mode live`: real Groq/Gemini/Supabase via `LLMClient`, every response cached in
    `evals/.cache/` (committed, ~1.4 MB, synthetic data only) so re-runs cost nothing;
    `--cache-only` re-renders without any API call; fresh calls are paced under Groq's 8K TPM.
  - Outputs `evals/results.md`, `evals/results.json` and `frontend/lib/eval-results.json`.
- `.github/workflows/evals.yml`: manual (`workflow_dispatch`) fake/live run, secrets by name only,
  results in the job summary and as an artifact. CI also lints `evals/` and runs the fake mode.
- `app/core/tracing.py`: every provider attempt in `LLMClient.structured()` is recorded (provider,
  model, step, tokens, latency, ok, estimated list-price cost). Optional Langfuse export over its
  OpenTelemetry endpoint (OTLP/HTTP JSON, no SDK dependency), on only when `LANGFUSE_PUBLIC_KEY`,
  `LANGFUSE_SECRET_KEY` and `LANGFUSE_HOST` are all set; fire-and-forget, every error swallowed.
  Spans carry metadata only (no prompts, outputs, CV/JD or transcript text); all calls of one HTTP
  request share a trace id derived from the request id. `llm.py` change: 4 lines.
- Engineering page: the eval placeholder is replaced by the committed results (run date + commit
  badge, headline strip, summary table, vector vs hybrid table) read from JSON at build time; the
  measured-numbers table gains eval-suite latency, tokens and cost per session. Still static.

#### Results (live, 2026-11-12, `openai/gpt-oss-20b` / `openai/gpt-oss-120b`, Gemini fallback)
- JD must-have recall 32/32, CV skill recall 67/67 (synthetic CVs are cleanly formatted).
- Gap detection: missing-skill recall 37/37, precision 37/40 (the 3 errors: skills only listed or
  closely related, labelled weak, judged missing); verdict agreement 89/92; 0 over-claims.
- Evidence quotes verbatim: 52/52 raw, 52/52 after validation (0 downgrades needed this run).
- Retrieval hit@5: vector-only 30/30, hybrid 30/30, keyword-only 16/30; MRR@5 0.90 vs 0.88. Hybrid
  did **not** beat vector-only on this set (mostly paraphrased queries); the Engineering page says so.
- Scoring: 30/30 inside the expected ranges; strict bands 27/30; consistency mean SD 0.18 over 3
  runs, 5/6 answers kept their band (max spread 1.4).
- Injection: 7/8 safe. **Open:** an answer that is only a pasted JSON object in our score format
  (`{"relevance": {"score": "5"}, ...}`) scored 5.0 on every criterion.
- Latency (LLM only): answer scoring p50 1.4 s / p95 5.8 s (n = 47); judge p50 1.9 s; analysis
  ≈ 7.0 s p50; ≈ 25K tokens per full session ≈ $0.0047 at Groq list prices; $0 on free tiers.

#### Not done / open
- No Langfuse keys were available, so the exporter is tested against a mock transport only, and
  there is no public demo trace yet.
- The JSON-shaped answer injection above: fixed in Phase 5 (see its Fixed section).

### Phase 5: Scoring and report (2026-11-12)

#### Added
- `POST /sessions/{id}/report` (SSE: `status` → `overview` → `status` → `done`). Built only for a
  completed interview (409 `interview_not_completed`). All numbers come from code
  (`backend/app/services/report.py`), from the per-answer rubric scores the interviewer saved:
  weighted dimensions (relevance 20%, technical accuracy 25%, depth 25%, structure 15%,
  communication 15%; N/A renormalized), follow-ups 70/30, readiness = 0.75 × interview + 0.25 × CV
  match, bands (Not ready yet / Getting there / Interview-ready / Strong), answer levels, distance to
  the next band, speech summary. Half-up rounding (Python's `round` is banker's rounding).
- One strong-model call (temperature 0.1, ~3K tokens in) writes the simulated hiring-manager
  reaction, 3 green / 3 red flags, strengths, improvements and a refreshed 7-day plan. Guardrails in
  code: flag quotes must exist in the referenced answer's transcript (else dropped), flags must
  point at a real answer, the verdict may move at most one step from what the score implies, plan
  URLs only from the curated catalog, Day 7 is a re-test. Deterministic fallback report if the LLM
  fails, labelled in the UI.
- Idempotency: the `reports` row is the lock (placeholder insert; the primary key rejects a second
  claim; stale claims expire after 120 s; a second tab waits for the first run). Cached reports are
  free; rate limit `report` (10/h per IP) + quota `report` (3/session) only on a fresh build.
- `GET /sessions/{id}/report`: report + share state, `email_configured`, `emailed_at`,
  `expires_at`, `is_demo`.
- `POST /sessions/{id}/report/share` `{action: create|revoke}`: 256-bit `secrets.token_urlsafe(32)`,
  one active link per report, revocable. `GET /reports/shared/{token}`: redacted copy (no session
  id, CV text or email; emails / phone numbers said in answers masked), `X-Robots-Tag: noindex,
  nofollow, noarchive`, `Referrer-Policy: no-referrer`, `Cache-Control: private, no-store`; dead once
  revoked, deleted or the session expires.
- `POST /sessions/{id}/email`: `backend/app/services/email.py`, an `EmailProvider` interface with a
  Resend implementation over the shared httpx client (no SDK). Off until `RESEND_API_KEY` and
  `EMAIL_FROM` are set (503 `email_not_configured`, button disabled with an explanation). Short
  summary + link, never transcripts or CV text; `Idempotency-Key` per report + hashed recipient;
  addresses and content never logged; masked "Sent to a•••@…" in the response. Rate limit `email`
  (5/h per IP) + quota `email` (3/session).
- `DELETE /sessions/{id}`: deletes the session; every table cascades (documents, chunks, analysis,
  questions, answers, interview state, report + share link, reminders, usage counters).
- Frontend `/session/[id]/report`: code-computed sections render from `overview` before the AI
  write-up; order from the research brief (readiness hero with formula, top 3 fixes, competency
  strip, simulated hiring-manager reaction, question cards with verified quotes marked in the
  transcript, delivery with a pace range bar, strengths, open gaps + plan, honest footer with the
  auto-delete date). Share sheet (includes / excludes, copy, revoke), email panel, Print / Save as
  PDF, Delete my data dialog (Cancel focused) → `/deleted`.
- `/r/[token]`: read-only banner, expiry, no actions, sample-CV CTA, noindex metadata, generic OG
  text; `next.config.ts` sends the noindex / no-referrer / no-store headers on `/r/*`.
- Print CSS (no PDF library): light theme, chrome hidden, all `<details>` opened on `beforeprint`,
  compact layout; a 6-question report prints on 5 A4 pages.
- Tests: `backend/tests/test_report.py` (formula, rounding, bands, clamp, quote verification,
  completed-only, claim / wait / cache, fallback, injection, ownership, quota, share lifecycle and
  redaction, email on/off/failure, Resend request shape, delete cascade);
  `supabase/tests/test_migrations.py` checks the reports lock, share-token uniqueness and cascade;
  `frontend/e2e/report.mock.py` (real Chrome, mocked API).

#### Fixed
- **Scoring injection (Phase 8 eval finding):** an "answer" that was pasted JSON in the scorer's own
  output format (`{"relevance": {"score": "5"}, ...}`) scored 5/5. Now the scoring prompt says the
  fenced transcript may imitate the output format and must then score 1, and code enforces it in
  `backend/app/agents/interviewer/tools.py`: `imitates_output_format` (2+ scorer field names used
  as keys, a bare JSON value, or >20% markup characters) floors every criterion at 1, marks the
  answer `off_topic` (the interviewer re-asks) and replaces the model's feedback with "Not a real
  answer". Separately, a score of 4-5 with no verified quote from the answer anywhere is capped at
  3. Tests in `backend/tests/test_interview.py`.

#### Changed
- Interview completion screen leads with "See your report".
- Landing: the report / email / share feature is **Live**; the "Report" step lost its badge.
- `/privacy`: email via Resend (summary only, on click), share links, Delete my data.
- `robots.txt` no longer disallows `/r/`: a disallowed page's noindex is never seen, so the
  header + meta tag do the job instead.
- `.env.example`: `BREVO_API_KEY` replaced by `RESEND_API_KEY` (provider still swappable).
- `streamAnalysis` and `streamReport` share one SSE reader in `frontend/lib/api.ts`.

#### Verified
- Backend: ruff, ruff format, mypy clean; pytest 339 passed, 1 xfailed. Migration smoke test (embedded
  Postgres) ALL OK.
- Frontend: lint, typecheck, prettier, `next build` clean; `e2e/report.mock.py` 7/7 and the
  analysis / interview / voice mocks still pass.
- Live (Groq, sample interview, fake DB): report in 4.9 s and 3.3 s, no Gemini fallback, 6/6 flag
  quotes verified; a transcript ordering "strong_yes" left the verdict at the score's `lean_no`.
- No new SQL: the `reports` table from the first migration already has every column.

### Phase 6: UI/UX, landing, engineering and privacy pages (2026-11-08)

#### Added
- Design system: semantic colour tokens with automatic dark mode (`prefers-color-scheme`), AA-checked
  text/background pairs, Geist via `next/font` (self-hosted), and hand-written primitives in
  `frontend/components/ui/` (`Button`/`ButtonLink`, `Card`, `Badge`, `Input`/`Textarea`/`Checkbox`/
  `Label`, `Container`/`SectionHeading`, inline SVG icons, one shared `focusRing`).
- Shared site header and footer on every page, a "Skip to content" link, and a 404 page.
- Landing page (`/`, statically generated and enforced with `ensureStatic`): hero with both CTAs, an
  HTML/CSS product preview of an analysis card, measured numbers, "How it works", feature cards with
  honest Live / In progress / Coming soon labels, "Built with", privacy note, FAQ (`<details>`) and a
  closing CTA.
- `/engineering` (static): HTML/CSS architecture diagram (no Mermaid: the CSP blocks CDN scripts and
  the library would outweigh the page), analysis data flow, the interview graph, 8 design decisions
  with trade-offs, measured latency table, eval table placeholder (Phase 8) and a security summary.
- `/privacy` (static): what is collected, AI/infra processors (Groq, Google Gemini, Supabase, Vercel)
  with links to their terms, a note on free-tier terms, retention (7-day expiry; the deletion cron
  is still pending), logging, and a contact section.
- Metadata: title template, description, Open Graph + Twitter card with a build-time generated OG
  image, `icon.svg`, `favicon.ico`, `apple-icon.png`, `robots.txt` and `sitemap.xml` (exclude
  `/session/*`, `/r/*`, `/api/*`). Owner placeholders in `frontend/components/site/config.ts`:
  `LINKEDIN_URL`, `CONTACT_EMAIL` (hidden while null).
- `docs/UX_REVIEW.md`: prioritized recommendations for the analysis and interview pages, with
  screenshots in `docs/ux-review/`.

#### Changed
- `/start`: numbered sections, dropzone states (idle, drag-over, file chosen, error, remove file),
  JD counter with "N more characters needed", options in one panel, consent text linking `/privacy`,
  inline validation on submit and a line that says what is still missing (`aria-disabled` instead
  of a silently disabled button). Session reuse on retry (B14) kept.
- `DemoButton` uses the shared button styles and shows a spinner while starting.

#### Verified
- `next build`: `/`, `/start`, `/engineering`, `/privacy`, `/opengraph-image`, `/robots.txt`,
  `/sitemap.xml`, `/icon.svg` are static (○). First-load JS (gzip, excluding the `nomodule`
  polyfill): ~141 KB on `/`, ~139 KB on `/engineering` and `/privacy`, ~146 KB on `/start`; CSS 11 KB.
- Lighthouse on `/` (local `next start`): desktop 99–100 / 100 / 100 / 100, LCP 0.7 s, CLS 0. Mobile
  (simulated slow 4G + 4× CPU on a busy machine) 77–92 performance, 100 accessibility (also on `/start`, `/engineering`, `/privacy`), 100 best
  practices, 100 SEO, LCP 2.5–3.0 s, CLS 0. The mobile LCP target (< 2.0 s) is not met locally;
  the minimal `/privacy` page scores the same range, so it is mostly framework hydration under CPU
  throttling. Re-measure on Vercel.
- Screenshots at 1280 and 390 px in light and dark for all public pages, no console errors, no
  horizontal overflow; keyboard-only pass (skip link, tab order, visible focus, FAQ with Enter).
- `e2e/interview.mock.py` and `e2e/analysis.mock.py` still pass with the new layout.

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
