# Flockit: notes for coding agents

Self-hosted control plane for an engineering org of people and AI developers: session visibility, tasks and
workflows dispatched to laptops (`flockit agent`) and runners (`flockit runner`), full transcripts and search. Monorepo:
`collector/` (Python 3.9+, stdlib only), `server/` (FastAPI, SQLAlchemy async, Alembic, Postgres),
`web/` (React 19, TypeScript, Tailwind 4, TanStack Query), `deploy/`, `docs/`.

## Commands

- `make dev-db`, `make dev-server`, `make dev-web`: local development
- `make test`: all suites. The server tests need Postgres (`FLOCKIT_TEST_DATABASE_URL`, default `localhost:55432/flockit_test`)
- `cd web && npx tsc -b`: typecheck the UI
- New migration after changing `models.py`: `cd server && FLOCKIT_DATABASE_URL=... .venv/bin/flockit-server revision -m "what changed"`

## Rules that are product decisions, not style

- No outbound network calls from the server or UI. Runners are the only component that talks to model providers and git hosts.
- Session metadata is limited to `redact.SESSION_FIELDS`; transcript text goes through `conversation.redact_text`. Any change needs redaction tests.
- The collector hook must never print to stdout, raise, or wait on the network.
- Every session has a required human owner; AI developers are recorded as the actor. Never reassign ownership in ingest.
- Every query returning sessions, transcripts, tasks or people goes through `scope.py` / `runs.visible_runs`.
- Nothing starts on a person's laptop without their consent (accept, or opted-in auto-start). Webhook-triggered work never auto-starts on a laptop.
- Anything user-controlled that reaches a shell is passed as an argument or read from a file, never interpolated. Workbench
  declarations are validated twice: in `routers/environments.py` and again in `collector/src/flockit/workbench.py`.
- Token kinds do not overlap: `collector` writes sessions and cannot read; `mcp` reads within its owner's role and cannot write.
- Slack and webhook text is untrusted input (`runs.UNTRUSTED_TRIGGERS`): it never auto-starts work on a person's machine, and
  the prompt says to treat it as data.
- Out of scope: code indexing/embeddings, IDE plugins, hosted SaaS.
