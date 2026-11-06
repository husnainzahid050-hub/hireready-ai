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
