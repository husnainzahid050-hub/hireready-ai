# Learning notes

One section per phase. Each concept points to the file where you can see it in action.

---

## Phase 0: Scaffolding

### 1. Monorepo
One Git repo holds two apps: `frontend/` (Next.js) and `backend/` (FastAPI). They deploy as
**two separate Vercel projects**, each with its own "Root Directory". One repo keeps the code,
issues, and CI in one place, while each app still deploys independently.

### 2. What "serverless" means for our backend
On Vercel, the FastAPI app becomes a **Vercel Function**. There is no server that's always on.
When a request arrives, Vercel starts (or reuses) an instance, runs your code, and may shut it down
later. This has two consequences that shape the whole project:
- **No memory between requests.** You can't keep the interview state in a Python variable.
  That's why the spec stores LangGraph state in Postgres (`interview_state`), added in Phase 3.
- **Limits.** Verified for the Hobby plan: 300 s max per request, 4.5 MB max request/response body,
  500 MB max Python bundle. That's why we use hosted AI APIs instead of installing PyTorch.

See: [backend/app/main.py](../backend/app/main.py). Vercel looks for a variable called `app` there.

### 3. ASGI and FastAPI
**ASGI** is the standard interface between a Python web server and an async Python app. FastAPI is an
ASGI app. Locally, `uvicorn` is the server; on Vercel, their runtime plays that role. Same code both ways.

### 4. Settings from environment variables
[backend/app/core/config.py](../backend/app/core/config.py) uses **pydantic-settings**: each field
maps to an env var (`groq_api_key` ↔ `GROQ_API_KEY`), is type-checked, and fails loudly if invalid.
Secrets use `SecretStr`, so `print(settings)` shows `**********` instead of your key.
Model names are env vars too, because providers rename models often.

### 5. Same-origin proxy (Next.js rewrites)
The browser only calls `/api/v1/...` on the **frontend's** domain. Next.js forwards it to the
backend (see `rewrites()` in [frontend/next.config.ts](../frontend/next.config.ts)). Benefits:
- No CORS headaches: the browser sees one origin.
- `BACKEND_URL` has no `NEXT_PUBLIC_` prefix, so it never ships in client JavaScript.

### 6. Security headers
Also in `next.config.ts`. Each one tells the browser to refuse a class of attack:
- **CSP (Content-Security-Policy):** a list of the only places scripts, images, and frames may load
  from. If an attacker injects a `<script src="evil.com">`, the browser blocks it.
  `frame-ancestors 'none'` stops other sites from embedding us in an iframe (clickjacking).
- **HSTS:** "only ever talk to me over HTTPS."
- **X-Content-Type-Options: nosniff:** don't guess file types (prevents some upload tricks).
- **Permissions-Policy:** only our own pages may use the microphone; camera and location are off.

Tradeoff we made: a strict CSP needs **nonces** (a random value per request), but nonces force every
page to render dynamically, and our landing page must be static and fast. So Phase 0 uses the
documented "without nonces" CSP; Phase 7 revisits this (e.g. hash-based SRI).

### 7. Error envelopes
Every error has the same shape, `{"error": {"code": "...", "message": "..."}}`, so the frontend
handles errors in one place. Unexpected crashes return a generic message; the real stack trace only
goes to the server logs. Validation errors list *which fields* failed but never echo the submitted
values, which could be someone's email or CV. See
[backend/app/core/errors.py](../backend/app/core/errors.py) and its tests.

### 8. Structured logs and request IDs
Logs are JSON lines, not free text, so a log tool can filter by `status=500` or `path=/api/v1/...`.
Every request gets an `X-Request-ID`. When a user reports a bug, that ID finds the exact log lines.
Rule for the whole project: **log IDs, never CV text, transcripts, or emails.**
See [backend/app/core/logging.py](../backend/app/core/logging.py).

### 9. CI (continuous integration)
[.github/workflows/ci.yml](../.github/workflows/ci.yml) runs on every push and PR: lint
(ruff/eslint/prettier), type checks (mypy/tsc), tests (pytest), a production build, and dependency
vulnerability audits (`pip-audit`, `npm audit`). A red CI means "don't merge."

### 10. Tests without the network
[backend/tests/](../backend/tests/) uses FastAPI's `TestClient`, which calls the app in-process.
No server and no internet are needed. Later phases will **mock** LLM calls the same way, so tests are
fast, free, and deterministic.

---

## Phase 1: Database and knowledge base

### 1. What embeddings are
An **embedding** is a list of numbers (here, 768 of them) that represents the *meaning* of a text.
Texts with similar meaning get vectors that point in similar directions, even with no words in common:
"explain overfitting" lands near "model memorizes the training data".
We measure closeness with **cosine similarity** (the angle between two vectors).
- We call Gemini's `batchEmbedContents` REST endpoint directly with httpx:
  [backend/app/services/embeddings.py](../backend/app/services/embeddings.py).
- **Task types:** documents are embedded with `RETRIEVAL_DOCUMENT` and questions with
  `RETRIEVAL_QUERY`. The model is trained so a query vector lands near the documents that answer it.
- **Normalization:** Gemini only normalizes full 3072-d vectors. We ask for 768-d (4x less storage) and
  L2-normalize them ourselves, so every vector has length 1. For unit vectors, cosine similarity is just
  a dot product.

### 2. Chunking
A whole knowledge file is too big and too mixed in topic to retrieve as one unit. We split it **by
heading** ([backend/app/services/chunking.py](../backend/app/services/chunking.py)). Each chunk keeps
its **heading path**, e.g. `Python > Question bank > Junior > What is a decorator?`. That path is put
at the top of the chunk text, so the embedding and the keyword index both "know" the context. The
path also gives us the **level** (junior/mid) for free.

### 3. pgvector and HNSW indexes
**pgvector** adds a `vector(768)` column type and distance operators to Postgres (`<=>` is cosine
distance). Comparing a query to every row is slow at scale, so we build an **HNSW index** (a graph of
"neighbour" links that lets search jump quickly toward the closest vectors). It is *approximate*: it
trades a little accuracy for a lot of speed. See
[supabase/migrations/20261106000001_init_schema.sql](../supabase/migrations/20261106000001_init_schema.sql).

### 4. Why hybrid search, and Reciprocal Rank Fusion (RRF)
- **Vector search** understands meaning but can miss exact terms like "GIL", "HAVING" or "STAR".
- **Full-text search** (a Postgres `tsvector` column with a GIN index) nails exact words but misses
  synonyms.
- **Hybrid search** runs both and merges the results. Their scores live on different scales, so
  instead of adding scores we fuse **ranks**:

  `score = 1/(k + rank_in_vector_results) + 1/(k + rank_in_keyword_results)`, with k = 50.

  A chunk that ranks well in *both* lists rises to the top, and a chunk found by only one list still
  counts. That's **RRF**: [supabase/migrations/20261106000002_hybrid_search.sql](../supabase/migrations/20261106000002_hybrid_search.sql).
  The same function searches the rubric knowledge base (filtered by competency/level) or **one
  session's CV** (filtered by `session_id`, so one user can never retrieve another user's CV).
  Phase 8 measures whether hybrid really beats vector-only (hit rate@5, MRR).

### 5. Row Level Security (RLS) and "deny by default"
Supabase exposes tables over a public REST API. RLS decides which rows each role can see. Our
design: the browser never talks to the database, only our backend does, using the **service role**
(which bypasses RLS). So we turn RLS **on** for every table with **no policies**, and also **revoke
all grants** from `anon`/`authenticated`. If the public anon key ever leaked, it could read nothing.
The new `sb_secret_...` keys are sent only in the `apikey` header; Supabase rejects them if they come
from a browser.

### 6. Idempotent ingestion
"Idempotent" means running it twice has the same effect as running it once.
[backend/app/services/knowledge.py](../backend/app/services/knowledge.py) identifies every chunk by
the SHA-256 **hash of its content**. Each run:
- skips chunks whose hash already exists (no embedding call, so no cost),
- embeds and inserts only new or changed chunks (in batches of up to 100),
- deletes chunks that disappeared from the file.

Edit one paragraph and only that chunk gets re-embedded.

### 7. Why no Supabase SDK
The official Python SDK bundles realtime, storage and auth clients we don't need. Four small httpx
calls ([backend/app/db/client.py](../backend/app/db/client.py)) keep the serverless bundle and cold
starts small, and are easy to mock in tests with `httpx.MockTransport`.

### 8. Retries with exponential backoff
APIs fail temporarily (429 rate limit, 503). [backend/app/core/http.py](../backend/app/core/http.py)
retries those with growing waits (0.5 s, 1 s, 2 s...) plus random **jitter**, so many clients don't
retry in sync, and it honours `Retry-After`. It never retries 4xx client errors, because those
won't fix themselves.

### 9. Testing SQL without a cloud account
[supabase/tests/test_migrations.py](../supabase/tests/test_migrations.py) starts a real embedded
Postgres with pgvector (`pgserver`) and recreates Supabase's roles. It then applies our migrations
and checks RRF ranking, filters, CV isolation between sessions, cascade deletes, RLS, and that
`anon` is denied. CI runs it on every push.

### 10. Lessons from running it for real (live keys, 2026-11-06)
Mocked tests passed, but the first real run found three problems that only live systems reveal:
- **Docs vs. reality:** Google's official schema says to send `outputDimensionality` inside
  `embedContentConfig`, but the live API ignored it and returned 3072 numbers. Sending the "deprecated"
  top-level field works. Our code **checks the vector size it gets back**, so it failed loudly instead of
  silently storing wrong data.
- **Model availability:** the Llama models listed in Groq's docs weren't available on this account.
  Model names live in env vars (`GROQ_FAST_MODEL`, `GROQ_STRONG_MODEL`), so switching to
  `openai/gpt-oss-20b` / `openai/gpt-oss-120b` changed no code.
- **Free-tier rate limits:** ingestion hit a per-minute quota (HTTP 429) after 136 of 157 chunks. The
  ingestion is idempotent, so re-running only embedded the missing 21, and a third run did nothing.
  Batch jobs now use a "patient" retry mode (waits up to 30 s) to outlast the quota by themselves.

Lesson: unit tests prove *your* logic; a quick live smoke test proves your *assumptions about other
systems*. Do both.

---

## Phase 2: Intake and gap analysis

### 1. Structured output: making the LLM return data, not prose
We never parse free text. Every LLM call sends a **JSON Schema** built from a Pydantic model
(`CVProfile`, `JobProfile`, `EvidenceJudgements`, `InsightsDraft` in
[backend/app/schemas/analysis.py](../backend/app/schemas/analysis.py)), and Pydantic validates the
reply. Groq's **strict mode** uses *constrained decoding*: at each step the model may only pick tokens
that keep the JSON valid for the schema. Strict mode requires every field to be `required` and every
object to have `additionalProperties: false`; `to_strict_schema()` in
[backend/app/services/llm.py](../backend/app/services/llm.py) converts Pydantic's schema to that.
**Lesson from live testing:** even strict mode once produced `"6"` instead of `6` for a day number.
The fix: don't ask the model for things code can do (we number the days ourselves).

### 2. Provider fallback
Groq is fast, but its free tier allows about 8K tokens per minute per model.
[llm.py](../backend/app/services/llm.py) tries Groq first, and on a 429, a 5xx or invalid JSON it falls
back to Gemini automatically. Model names are env vars, which mattered twice: Llama wasn't available on
the account, and `gemini-2.5-flash` was retired for new users. The `gpt-oss` models "think" before
answering; `reasoning_effort: low` keeps those hidden tokens cheap.

### 3. Token budgets are a design constraint
The first version of the skill judge sent the same CV excerpts once per skill: 7,016 prompt tokens,
which hit the per-minute limit. Now each excerpt is sent **once** with an id (`[E1]`, `[E2]`, ...) and
skills just reference the ids: 1,113 tokens for the same information. See `judge_skills` in
[backend/app/services/analysis.py](../backend/app/services/analysis.py).

### 4. RAG over the CV, plus the anti-hallucination guard
For each JD skill we run hybrid search over *this session's* CV chunks (one batched embedding call for
all skills, then parallel DB searches). The LLM judges strong / weak / no evidence and must quote the
CV. Then **code checks that the quote really exists** in the CV
([backend/app/services/evidence.py](../backend/app/services/evidence.py)): both strings are normalized
(case, whitespace, curly quotes, dashes, bullets), and the quote must be a substring. If it isn't, the
verdict becomes `no_evidence`. The LLM proposes; deterministic code verifies.

### 5. Explainable scoring
The match score is plain arithmetic in
[backend/app/services/scoring.py](../backend/app/services/scoring.py):
`100 x (0.7 x must-have coverage + 0.2 x nice-to-have coverage + 0.1 x seniority fit)`, with
strong = 1, weak = 0.5 and none = 0. The UI shows each component and the formula, so users (and
recruiters) can check it. LLMs are bad at producing consistent numbers; code is perfect at it.

### 6. Guardrails in code, not just in prompts
The prompt *asks* the model to use only curated resource URLs and real quotes; `sanitize_insights`
*enforces* it. Unknown URLs are removed, unverifiable strength quotes are dropped, and the plan is cut to
exactly 7 days. Prompt instructions are requests; code is a guarantee.

### 7. Prompt-injection defence (first layer)
CV and JD text goes inside `<cv>`, `<jd>` or `<evidence>` tags, and every system prompt says that text
inside those tags is data, never instructions. `wrap_untrusted` also neutralizes a fake closing tag
(`</cv>`) hidden in the user's text. Phase 7 adds adversarial tests.

### 8. Upload security
[backend/app/services/parsing.py](../backend/app/services/parsing.py) checks the size first, then the
declared MIME type, then the **magic bytes** (`%PDF-` or `PK\x03\x04`), because the browser's MIME type
is only a claim. Next come the page count, a zip-bomb guard for DOCX (total unpacked size), and finally
a check for real text (scanned PDFs have none). Files are parsed in memory, and only the extracted text
is kept.

### 9. Guest ownership without accounts
Creating a session returns a random 32-byte **guest token**. The database stores only its SHA-256 hash
([backend/app/core/security.py](../backend/app/core/security.py)), and comparisons use
`hmac.compare_digest` (constant time). Every session endpoint returns the same 404 for "doesn't exist"
and "not yours", so attackers can't probe for valid ids. The browser keeps the token in `localStorage`,
which is why opening the link in another browser is blocked.

### 10. Server-Sent Events (SSE) for progressive results
`POST /sessions/{id}/analyze` returns a `text/event-stream`: lines like `event: gaps` followed by
`data: {...}`. The UI fills in each section as its event arrives (the first update comes in about
0.5 s). Browsers' `EventSource` only supports GET without custom headers, so
[frontend/lib/api.ts](../frontend/lib/api.ts) reads the stream with `fetch` and parses the events itself.
A finished analysis is saved, and a second request returns it instantly with zero LLM calls.

### 11. Next.js 16: a static shell plus a streamed dynamic part
With `cacheComponents` on, a page that reads the URL (`params`) can't be fully static. So the analysis
page is a static shell, and the session-specific part (`useParams`) sits inside `<Suspense>`. The build
output marks it as Partial Prerender.

### 12. Testing like a user
Besides the 96 unit and API tests (fake DB plus a scripted fake LLM), the flow was driven in a real
headless Chrome. The test clicks "Try with a sample CV", waits for the streamed results, reloads (served
from cache) and opens the page in a second browser (blocked). It also checks form validation, on both
desktop and mobile screen sizes.

## Phase 3 (frontend): the interview page

### 1. A thin API client that mirrors the contract
[frontend/lib/types.ts](../frontend/lib/types.ts) has `InterviewTurn` and `Question` exactly as the backend
returns them, and [frontend/lib/api.ts](../frontend/lib/api.ts) has `getInterview`, `startInterview` and
`submitAnswer`. Every call sends `X-Guest-Token`. Errors become an `ApiError` with the envelope's `code`,
and on 429 it also carries `retryAfter` (parsed from the `Retry-After` header, in seconds or as an HTTP date).

### 2. The server owns the interview; the page only renders turns
Each answer returns the next `InterviewTurn`, and `GET /interview` returns the same shape plus the full
history. So **resume after reload** is just "GET and render". A 409 `not_started` shows the start
screen. See [frontend/components/interview/interview-view.tsx](../frontend/components/interview/interview-view.tsx).

### 3. Never lose what the user typed
The draft is cleared only after the server accepts the answer. On 503 `ai_unavailable` or a network
error, the text stays in the box and "Retry" resends it. The draft is also saved in `sessionStorage`
(keyed by question id), so it survives a reload. On 400 `wrong_question` (for example, another tab
answered first) the page refetches the state, and keeps the text unless the server already has it.

### 4. Optimistic UI
While an answer is in flight, it appears in the transcript as "Sending…" and the interviewer shows
"Interviewer is thinking…". The textarea is `readOnly` (not `disabled`) so keyboard focus stays put.

### 5. Accessibility details
- A polite `aria-live` region announces each new question ("Question 3 of about 6: …").
- After a new question, focus moves to the answer box (`preventScroll`) and the question scrolls into view
  (instantly when `prefers-reduced-motion` is set).
- Practice mode is a native checkbox with `role="switch"`, so Space toggles it and screen readers read
  "on/off". Ctrl/⌘+Enter submits.
- The transcript is a disclosure button (`aria-expanded`) on phones and an always-open sidebar from `lg`.
- Animations use only `transform` (the `bars` keyframes in [frontend/app/globals.css](../frontend/app/globals.css))
  and are switched off with `motion-reduce:`.

### 6. Built for voice later
[frontend/components/interview/parts.tsx](../frontend/components/interview/parts.tsx) has an
`InterviewerStatus` of `listening | thinking | speaking` and an `InterviewerPanel` with a `controls` slot.
In Phase 4, `speechSynthesis` will drive "speaking", and a recorder will sit next to
[answer-composer.tsx](../frontend/components/interview/answer-composer.tsx). Both will call the same
`onSubmit` path.

### 7. Code splitting for free
App Router gives each route its own client chunk. The interview code (about 10.6 KB gzipped) loads only
on `/session/[id]/interview`. The page is a static shell with a skeleton fallback inside `<Suspense>`
(same pattern as the analysis page, see Phase 2 note 11), and the skeleton matches the real layout, so
there is no layout shift.

### 8. Testing against a mocked API
[frontend/e2e/interview.mock.py](../frontend/e2e/interview.mock.py) runs real Chrome against
`next start`. It answers every `/api/v1/**` call from a small fake state machine (`page.route`), so the
UI could be built before the backend was ready. It covers start, 6 questions plus a follow-up, reload
and resume, 503 retry, 429 wait, `wrong_question`, completion, mobile light/dark and "no token". It
also fails if the browser logs any console error.
