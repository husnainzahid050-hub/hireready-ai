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
