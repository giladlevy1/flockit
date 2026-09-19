# Flockit: notes for coding agents

Self-hosted control plane for R&D: every coding session, human and AI, in one view. Monorepo:
`collector/` (Python 3.9+, stdlib only), `server/` (FastAPI, SQLAlchemy async, Alembic, Postgres),
`web/` (React 19, TypeScript, Tailwind 4, TanStack Query), `deploy/`, `docs/`.

## Commands

- `make dev-db`, `make dev-server`, `make dev-web`: local development
- `make test`: all suites. The server tests need Postgres (`FLOCKIT_TEST_DATABASE_URL`, default `localhost:55432/flockit_test`)
- `cd web && npx tsc -b`: typecheck the UI
- New migration after changing `models.py`: `cd server && FLOCKIT_DATABASE_URL=... .venv/bin/flockit-server revision -m "what changed"`

## Rules that are product decisions, not style

- No outbound network calls anywhere (server, UI, collector). Fonts and assets are bundled.
- The collector sends only fields in `redact.SESSION_FIELDS`. Changing it needs tests and a README update.
- The collector hook must never print to stdout, raise, or wait on the network.
- Every session has a required human owner. Never reassign ownership in ingest.
- Every query returning sessions or people goes through `scope.py`.
- Out of scope: orchestration, running agents, code indexing/embeddings, IDE plugins, PR review, hosted SaaS.
