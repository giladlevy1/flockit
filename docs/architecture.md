# Architecture

Flockit M0 has three parts, all running inside the customer's network.

```
 developer laptop                              your network (docker compose)
┌───────────────────────────────┐             ┌──────────────────────────────────┐
│ Claude Code                   │             │ flockit (one container)          │
│   │ hooks (stdin JSON)        │             │   FastAPI  /api/*                │
│   ▼                           │   HTTP(S)   │   React UI  /                    │
│ flockit hook                  │ ──────────▶ │   collector package /downloads/* │
│   allowlist → scrub → outbox  │  metadata   │   sweeper (asyncio task)         │
│   detached `flockit flush`    │    only     │            │                     │
└───────────────────────────────┘             │            ▼                     │
                                              │ postgres (not published)         │
                                              └──────────────────────────────────┘
```

## Collector (`collector/`)

- **Entry point:** Claude Code runs `<venv python> -m flockit hook` for `SessionStart`,
  `UserPromptSubmit`, `Stop` and `SessionEnd`, passing a JSON document on stdin.
- **Event building** (`hook.py`): one hook call becomes at most one event. Repo, branch and task ref are
  computed once per session and cached in `~/.flockit/sessions/<id>.json`. The model and Claude Code
  version come from the tail of the transcript, reading two identifier fields and never message content.
- **Redaction** (`redact.py`): the security boundary. An explicit allowlist of ten fields, each with a
  validator that normalises or drops the value, then a scrubber for credential shapes. Tested in
  `tests/test_redact.py`.
- **Delivery** (`outbox.py`, `transport.py`): events are appended to a locked JSONL outbox, then a
  detached `flockit flush` process sends them. A down server costs the session nothing; events wait,
  capped at 10,000.
- **Install** (`claude_settings.py`): merges four hook entries into `~/.claude/settings.json`, touching
  nothing else and keeping a one-time backup. `flockit uninstall` removes exactly those entries.
- **No dependencies.** Standard library only, Python 3.9+.

### Task reference detection

In order: `FLOCKIT_TASK_REF` in the environment, then the branch name (`ENG-123`, `gh-42`,
`issue/42`), then the first prompt that mentions a ticket key or an issue URL. Only the extracted
reference is sent, with any query string removed.

## Server (`server/`)

- **FastAPI + SQLAlchemy 2 (async) + asyncpg + Alembic.** Migrations run on start.
- **Auth** (`deps.py`): local accounts with Argon2 hashes and an httpOnly `SameSite=Lax` cookie backed by
  a `login_session` row (SHA-256 of the cookie only). Mutating requests need `X-Flockit-Request: 1`,
  which cross-origin pages cannot send without a CORS preflight the server never grants. Collector
  tokens (`flk_…`) are separate, stored as SHA-256, and valid only for ingest. `user.auth_provider` and
  `user.external_subject` exist so SSO can be added without changing the user model.
- **Ingest** (`ingest.py`): idempotent by `event_id`; upserts the session with
  `INSERT … ON CONFLICT DO NOTHING` followed by `SELECT … FOR UPDATE`, so concurrent retries serialise.
  `started_at` only moves earlier, `last_seen_at` only later, empty values never erase, and a session's
  owner can never change.
- **Scope** (`scope.py`): every query that returns sessions or people is filtered through one of two
  functions. Filters narrow the scope; they can never widen it.
- **Sweeper** (`main.py`): every 5 minutes, open sessions with no activity for
  `FLOCKIT_ABANDON_AFTER_HOURS` are marked `abandoned`. Later activity reopens them.

### Outcomes

| Outcome | Meaning |
|---|---|
| `completed` | the developer ended the session (`prompt_input_exit`, `logout`, `clear`) |
| `abandoned` | no activity for the abandonment window, never ended |
| `errored` | reserved for agents that report a failed end |
| `unknown` | still open, or ended for a reason we cannot classify (headless `claude -p` ends with `other`) |

A session's **status** is derived at read time: `live` (activity within 15 minutes), `idle` (open but
quiet) or `ended`.

## Data model

Only `session` (plus identity tables) is written in M0. The rest is schema, so later milestones add
behaviour without migrating existing data.

| Table | M0 | Notes |
|---|---|---|
| `organization`, `user`, `team`, `team_member` | written | every row carries `org_id` |
| `login_session`, `api_token` | written | hashes only |
| `session` | written | required `human_owner_id`, `origin` (`human`/`workflow`), `task_ref`, `workflow_run_id` |
| `ingest_event` | written | seen event ids, for idempotency |
| `workflow_run` | schema only | the seam for a future workflow runner |
| `fact` | schema only | M2: `claim`, `producing_command`, `scope`, `state`, `ttl_seconds`, `last_verified_at` |
| `decision` | schema only | M5: `statement`, `origin` (review comment, correction, revert), `superseded_by_id` |
| `retrieval` | schema only | M2: `session_id` is nullable, so agents Flockit did not start can retrieve |

## Web (`web/`)

React 19, TypeScript, TanStack Query, Tailwind 4, React Router 7. No component library. Everything,
fonts included, is bundled into the build and served by the Flockit server; the Content-Security-Policy
forbids any other origin. The Sessions page polls every 5 seconds. Filters, date range, page and the
open session all live in the URL.
