# Contributing to Flockit

Thanks for helping. A few things matter more here than in most projects.

## Before you write code

**Check the scope.** Flockit deliberately does not do orchestration, agent execution, code indexing,
embeddings, IDE plugins, PR review, or hosted SaaS (see the README). Pull requests that add those will be
declined, however good. If you are unsure, open an issue first.

**Never add an outbound call.** No telemetry, analytics, update checks, CDN assets, or third-party APIs,
from the server, the UI or the collector. `docs/network-trace.md` describes how we verify this.

**The collector's wire format is a security boundary.** Adding a field to
`collector/src/flockit/redact.py:SESSION_FIELDS` needs a validator, tests in `test_redact.py`, an update
to the table in the README, and a clear reason. `test_allowlist_is_exactly_these_fields` fails on
purpose until you do.

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
