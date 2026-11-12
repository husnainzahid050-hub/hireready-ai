# Release checklist (production deploy + smoke test)

Use this for the Phase 9 production release and for any later release that changes the schema or
environment. Work top to bottom; each box is something a person checks, not something to assume.
Items marked **(Phase N)** only apply once that phase is merged into `main`.

`TODO(final)`: after Phases 5, 7 and 8 merge, remove the "(Phase N)" qualifiers that no longer
apply and add anything new those branches introduced (check each branch's CHANGELOG entry and
`.env.example` diff).

## 0. Before you start

- [ ] `main` is green in CI (backend lint/type/tests, migration smoke test, frontend lint/type/build, `pip-audit`, `npm audit`).
- [ ] Locally: `cd backend && ruff check . && mypy app && pytest` and `cd frontend && npm run lint && npm run typecheck && npm run build`.
- [ ] Mocked browser tests pass against `next start -p 3001`: `python frontend/e2e/analysis.mock.py`, `interview.mock.py`, `voice.mock.py`, and `report.mock.py` **(Phase 5)**.
- [ ] `CHANGELOG.md` has the release entry; `README.md` has no `TODO(final)` left that you can already fill (`grep -rn "TODO(final)" README.md docs frontend/app frontend/components`).
- [ ] Decide the production domain. If it isn't the default `*.vercel.app` URL, add it to the frontend project and use it everywhere below as `<FRONTEND_URL>`.

## 1. Accounts (all free tier)

| Service | Needed for | Status |
|---|---|---|
| Vercel (two projects: `frontend/`, `backend/`) | Hosting | Exists |
| Supabase | Database + pgvector | Exists |
| Groq | LLM + Whisper | Exists |
| Google AI Studio (Gemini) | Fallback LLM + embeddings | Exists |
| Upstash Redis | Per-IP rate limits **(Phase 7)** | [ ] create a Redis database, copy the REST URL + token |
| Cloudflare Turnstile | Bot check on session creation **(Phase 7)** | [ ] create a widget for `<FRONTEND_URL>` (and `localhost` for dev), copy site key + secret |
| Resend | "Email me this report" **(Phase 5)** | [ ] verify a sending domain (`onboarding@resend.dev` only mails your own address), create an API key |
| Langfuse Cloud | Optional tracing **(Phase 8)** | [ ] create a project, copy public/secret key and the host for its region |

## 2. Database migrations (Supabase SQL editor)

The live project has `20261106000001_init_schema.sql` and `20261106000002_hybrid_search.sql`.

- [ ] Run `supabase/migrations/20261106000004_security.sql` (`session_usage` + `consume_quota()`). **Without it, uploads, analyses and interview turns fail with 500.**
- [ ] Run `supabase/migrations/20261106000005_analysis_claim.sql` (`sessions.analysis_started_at` + `claim_analysis()`).
- [ ] Check:
  ```sql
  select proname from pg_proc where proname in ('consume_quota', 'claim_analysis');  -- 2 rows
  select column_name from information_schema.columns
   where table_name = 'sessions' and column_name = 'analysis_started_at';             -- 1 row
  ```
- [ ] Phase 5 (report): no new migration on the `report-agent` branch at the time of writing (the `reports` table already exists). Re-check `supabase/migrations/` after the merge.
- [ ] Phase 7: run any new migration it adds (e.g. for cleanup or reminders). `TODO(final)`: list file names here.
- [ ] Re-check RLS: `select relname, relrowsecurity from pg_class where relnamespace = 'public'::regnamespace and relkind = 'r';` → every row `true`.
- [ ] Knowledge base is ingested: `select count(*) from knowledge_chunks;` → 157 (or the current count from `python -m scripts.ingest_knowledge --dry-run`).
- [ ] Empty the table in `supabase/PENDING_MIGRATIONS.md` once applied.

## 3. Environment variables

Set these in **Vercel → Project → Settings → Environment Variables**, scope **Production** (and
Preview if you use preview deploys). Never put a secret in a `NEXT_PUBLIC_` variable.

### Backend project (root `backend/`)

| Variable | Value | Notes |
|---|---|---|
| `APP_ENV` | `production` | Hides `/docs` (Vercel's `VERCEL_ENV` also does) |
| `APP_BASE_URL` | `<FRONTEND_URL>` | Used for links in emails and share links |
| `ALLOWED_ORIGINS` | `<FRONTEND_URL>` | Comma-separated, no `*` (refused at startup) |
| `GROQ_API_KEY` | secret | |
| `GROQ_FAST_MODEL` | `openai/gpt-oss-20b` | Re-check the model list at console.groq.com before release |
| `GROQ_STRONG_MODEL` | `openai/gpt-oss-120b` | |
| `GROQ_STT_MODEL` | `whisper-large-v3-turbo` | |
| `GEMINI_API_KEY` | secret | |
| `GEMINI_TEXT_MODEL` | `gemini-3.5-flash` | Fallback model |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Must match what the knowledge base was ingested with |
| `EMBEDDING_DIM` | `768` | Must match `vector(768)` in the schema |
| `SUPABASE_URL` | project URL | |
| `SUPABASE_SERVICE_ROLE_KEY` | `sb_secret_...` | Backend only, never the frontend |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | **(Phase 7)** | Rate limits are a no-op until set |
| `TURNSTILE_SECRET_KEY` | **(Phase 7)** | **Only after** the frontend renders the widget and sends `X-Turnstile-Token`, or every session creation returns 403 |
| `RESEND_API_KEY`, `EMAIL_FROM` | **(Phase 5)** | `EMAIL_FROM` on the verified domain, e.g. `HireReady AI <reports@yourdomain>`. Email is disabled (button greyed out) until both are set |
| `CRON_SECRET` | random, ≥ 32 chars **(Phase 7)** | Vercel sends it as `Authorization: Bearer ...` to cron paths |
| `OUTBOUND_WEBHOOK_URL`, `OUTBOUND_WEBHOOK_SECRET` | optional **(Phase 7)** | HMAC-signed webhook (e.g. n8n) |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | optional **(Phase 8)** | Tracing is off unless all three are set |

### Frontend project (root `frontend/`)

| Variable | Value | Notes |
|---|---|---|
| `BACKEND_URL` | the backend project's production URL | Server-side only (used by the `/api/*` rewrite); must not be `NEXT_PUBLIC_` |
| `SITE_URL` | `<FRONTEND_URL>` | Optional; canonical URL for OG tags, robots and sitemap. Defaults to Vercel's production URL |
| `NEXT_PUBLIC_TURNSTILE_SITE_KEY` | site key **(Phase 7)** | The only public variable |

- [ ] Redeploy **after** changing variables (Vercel applies them to new deployments only).
- [ ] `frontend/components/site/config.ts`: `LINKEDIN_URL` and `CONTACT_EMAIL` filled in (or deliberately left `null`, which hides them).

## 4. Deploy order

1. [ ] Migrations (section 2).
2. [ ] Backend env vars, then deploy the backend. Check `GET <BACKEND_URL>/api/v1/health` → `"status": "ok"`, `environment: "production"`, every dependency `configured`.
3. [ ] `GET <BACKEND_URL>/api/v1/docs` → 404 (docs hidden in production).
4. [ ] Frontend env vars, then deploy the frontend. Check `GET <FRONTEND_URL>/api/v1/health` works through the rewrite.
5. [ ] **(Phase 7)** Cron: confirm the `crons` entry in `backend/vercel.json` is listed under the backend project's **Settings → Cron Jobs**. Hobby allows once a day. Trigger each job once by hand with `curl -H "Authorization: Bearer $CRON_SECRET" <BACKEND_URL>/api/v1/cron/cleanup` (and `/reminders`); a request without the header must get 401/403.
6. [ ] **(Phase 7)** Turnstile: deploy the frontend with the site key first, confirm `/start` shows the widget and the demo button still works, **then** set `TURNSTILE_SECRET_KEY` on the backend and redeploy it.
7. [ ] **(Phase 7)** Rate limits: after Upstash is set, check from two networks that the limiter sees the browser's IP and not Vercel's egress IP (see `docs/SECURITY.md`, "Controls pending").

## 5. Headers and basics

- [ ] `curl -sI <FRONTEND_URL>/` shows `Content-Security-Policy`, `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Permissions-Policy` with `microphone=(self)`.
- [ ] `curl -sI <FRONTEND_URL>/api/v1/health` shows `Cache-Control: no-store`.
- [ ] **(Phase 5)** `curl -sI <FRONTEND_URL>/r/<token>` shows `X-Robots-Tag: noindex`.
- [ ] `<FRONTEND_URL>/robots.txt` and `/sitemap.xml` use the production domain.
- [ ] Share `<FRONTEND_URL>` in a LinkedIn post preview (or an OG debugger): title, description and image render.
- [ ] Lighthouse on `/` (mobile and desktop) on the deployed site. Record the numbers in the CHANGELOG. `TODO(final)`: results.

## 6. Manual smoke test

Run the whole path twice: **desktop Chrome** (latest, 1280 px) and **a real phone** (Android Chrome
or iOS Safari, on mobile data, not Wi-Fi). Use a private window so there is no old guest token.
Time the recruiter path with a stopwatch.

### 6.1 Recruiter path (target: landing → report in under 90 s of waiting time)

The 90 s target counts the time the user waits for HireReady, not the time spent answering. Note
both: "waiting" (sum of spinners and streams) and "total" (wall clock including your answers).

| Step | Expect | Desktop | Phone |
|---|---|---|---|
| Open `<FRONTEND_URL>` | Page renders, no layout shift, trust strip visible under the CTAs | [ ] | [ ] |
| Click **Try with a sample CV** | Analysis page opens and the first status appears within ~1 s | [ ] | [ ] |
| Analysis streams | Score with formula, gap cards with a green **verified** quote and at least one honest "no evidence", likely questions, 7-day plan | [ ] ___ s | [ ] ___ s |
| **Start interview**, choose **Voice** | Mic permission prompt; question read aloud with caption; mute and replay work | [ ] | [ ] |
| Answer Q1 by voice (one short, deliberately shallow answer) | "Transcribing…", then a **follow-up that refers to what you said** | [ ] ___ s | [ ] ___ s |
| Answer the rest (mix voice and text; use the Voice / Text switch or **Type instead** once) | Progress "Question X of ~6"; each turn returns in a few seconds | [ ] | [ ] |
| Finish → **See your report** **(Phase 5)** | Report streams: readiness score + band, **How is this calculated?** shows the formula, question cards with transcript quotes and an improved answer, speech section (pace, fillers) | [ ] ___ s | [ ] ___ s |
| **Waiting time total** | **< 90 s** | ___ s | ___ s |

### 6.2 Report actions (Phase 5)

| Step | Expect | Desktop | Phone |
|---|---|---|---|
| **Create share link**, open it in another browser / incognito | Read-only report, no CV text, no email, banner says it is shared; "Try with a sample CV" CTA | [ ] | [ ] |
| Revoke the link, reload it | Friendly "revoked, expired or deleted" page | [ ] | [ ] |
| **Print / Save as PDF** | Print preview is clean: no buttons, details expanded, readable on A4 | [ ] | [ ] |
| **Email me this report** (to your own address) | Masked "Sent to" line; email arrives with the summary and a link, no transcripts | [ ] | n/a |
| **Delete my data** | Confirmation dialog (Cancel focused) → `/deleted`; the session URL and the old share link now 404 | [ ] | [ ] |

### 6.3 Own CV path

| Step | Expect | Desktop | Phone |
|---|---|---|---|
| `/start`: upload a text-based PDF CV, paste a real JD | Dropzone states, character counter, consent required | [ ] | [ ] |
| Upload a scanned PDF / a `.png` renamed to `.pdf` / a 3 MB file | Clear errors, nothing crashes | [ ] | n/a |
| Run analysis → interview in **text** mode, practice mode on | Practice feedback after each answer | [ ] | [ ] |

### 6.4 Failure and edge cases

- [ ] Deny the microphone → the page explains it and offers typing.
- [ ] Turn on airplane mode mid-answer → friendly network error, the typed answer is not lost, Retry works.
- [ ] Open the analysis URL in another browser → "this session belongs to another browser" panel.
- [ ] Reload during the interview → it resumes on the same question.
- [ ] Dark mode (system setting) on `/`, analysis, interview, report: readable, no white flashes.
- [ ] Keyboard only on `/` and `/start`: skip link, visible focus, FAQ opens with Enter.
- [ ] Vercel → backend → Logs: no CV text, no emails, no stack traces in the requests you just made.

## 7. After the release

- [ ] Tag the release commit (`git tag v1.0.0`) and push the tag.
- [ ] GitHub repo **About**: live URL, description (the README one-liner), topics `rag`, `langgraph`, `fastapi`, `nextjs`, `pgvector`, `llm-evals`. Pin the repo on your profile.
- [ ] Record the demo video and GIF ([DEMO_SCRIPT.md](DEMO_SCRIPT.md)) on the production site and add them to the README.
- [ ] Fill every `TODO(final)` in `README.md` from `evals/results.md` and the smoke-test timings above.
- [ ] Watch Groq / Gemini / Supabase / Vercel usage dashboards for the first days after posting the link.
- [ ] One week later: confirm the cleanup cron deleted sessions older than 7 days **(Phase 7)**: `select count(*) from sessions where expires_at < now() - interval '1 day';` → 0.
