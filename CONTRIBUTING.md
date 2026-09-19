# Contributing to Flockit

Thanks for helping. A few things matter more here than in most projects.

## Before you write code

**Check the scope.** Flockit does not do code indexing, embeddings, IDE plugins or hosted SaaS (see the README
and `docs/decisions.md`). If you are unsure whether something fits, open an issue first.

**Never add an outbound call from the server or the UI.** No telemetry, analytics, update checks, CDN assets or
third-party APIs. Runners are the only component that talks to model providers and git hosts.
`docs/network-trace.md` describes how we verify this.

**Redaction is a security boundary.** Session metadata is limited to `redact.SESSION_FIELDS`
(`test_allowlist_is_exactly_these_fields` fails on purpose when it changes); transcript text goes through
`conversation.redact_text`. Changes need tests in `test_redact.py` / `test_conversation.py`.

**Consent is a security boundary.** Nothing may start on a person's machine unless they accepted the task or opted
into auto-start, and webhook-triggered work never auto-starts on a laptop. Anything user-controlled that reaches a
shell must be passed as an argument or read from a file.

## Setup

```bash
make dev-db        # Postgres on :55432
make dev-server    # API on :8080 (reload)
make dev-web       # UI on :5173 (hot reload, proxies the API)
make test
```

You need Docker, Python 3.12 with [uv](https://docs.astral.sh/uv/), and Node 22. The collector itself
supports Python 3.9+, and CI runs it on 3.9, 3.12 and 3.13.

To load demo data into your dev database: `cd server && FLOCKIT_DATABASE_URL=... .venv/bin/flockit-server seed-demo`
(empty database only).

## Pull requests

- Keep them small and focused. Include tests for behaviour changes.
- `make lint test` must pass.
- For UI changes, include a screenshot in light and dark mode.
- Schema changes need an Alembic migration (`server/src/flockit_server/migrations/versions/`).

By contributing you agree your contribution is licensed under Apache 2.0.
