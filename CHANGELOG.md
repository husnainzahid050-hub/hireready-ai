# Changelog

All notable changes per build phase. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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
