# Architecture

Three kinds of process, all inside the customer's network, plus the Postgres they share.

```
 developer laptop                           your network                                  runner host (Docker)
┌─────────────────────────────┐            ┌────────────────────────────────────┐        ┌───────────────────────────────┐
│ Claude Code ──hooks──▶ flockit hook      │ flockit server (one container)     │        │ flockit runner                │
│   (redact, outbox, flush) ───────────────▶  ingest · scope · search           │◀───────│  long-poll · stream sessions  │
│      ▲                      │  HTTP(S)   │  tasks · workflows · scheduler     │        │  ┌─────────────────────────┐  │
│      └── flockit mcp ────────────────────▶  webhooks · /api/slack (inbound)   │        │  │ sandbox per task        │  │
│                             │            │  web UI · /install.sh              │        │  │ clone → agent → push    │──┼──▶ model API,
│ flockit agent ◀──long-poll───────────────│            │                       │        │  └───────────┬─────────────┘  │    git host,
│   notify · worktree · open  │            │            ▼                       │        │  ┌───────────┴─────────────┐  │    Slack reply
│   terminal or run headless  │            │  postgres (not published)          │        │  │ workbench (kept)        │  │
└─────────────────────────────┘            │                                    │        │  │ postgres · cache        │  │
                                           │                                    │        │  └─────────────────────────┘  │
  GitHub, Jira, Sentry, Slack ──inbound───▶└────────────────────────────────────┘        └───────────────────────────────┘
```

The one rule the picture encodes: **arrows leave the network only from a runner.** The server and the UI never open an
outbound connection, which is why a webhook or a Slack command is answered in the response to that same request, and why a
Slack result is posted by the runner that did the work.

## Server (`server/`)

FastAPI, SQLAlchemy 2 (async), asyncpg, Alembic (migrations run on start), croniter.

| Module | Responsibility |
|---|---|
| `ingest.py` | Idempotent, out-of-order-safe session ingest; transcript messages (dedup by entry id), token usage, files touched; links sessions to tasks; attribution (owner is always a person, actor may be an AI developer) |
| `scope.py`, `runs.visible_runs` | The only definitions of who sees what. Filters narrow scope; they never widen it |
| `queries.py` | Sessions list, summary (KPIs, overlaps, model mix, top repos), facets |
| `runs.py` | Task lifecycle, assignment rules, prompt templating, webhook filters, audit helper |
| `routers/tasks.py` | Task API and the per-person inbox |
| `routers/workflows.py` | Workflows, run now, webhook endpoint, `run_due_schedules` (advisory-locked, safe with replicas) |
| `routers/machines.py` | Laptop agent and runner APIs: long-poll claims with `FOR UPDATE SKIP LOCKED`, per-task ingest tokens, status reports, stuck-task detection |
| `routers/search.py` | Transcripts, files, org-wide full-text search (`to_tsvector`, GIN index, `ts_headline`) |
| `routers/agents.py` | AI developers (including the per-developer profile: workbench, expertise from past work, tasks, sessions, workflows), runners, audit log |
| `routers/environments.py` | Workbenches: the declaration of the services an AI developer develops against, validated before it can reach a runner's command line |
| `routers/slack.py` | Slash commands and events. Signature-verified, inbound only; account linking by a code the person types in Slack |
| `main.py` | App, security headers (strict CSP), SPA serving, background sweeper (abandoned sessions, stuck tasks) and scheduler |

### Task lifecycle

```
offered ──accept──▶ queued ──claim──▶ starting ──session starts──▶ running ──▶ succeeded | failed
   └──decline──▶ declined            (any active state) ──cancel──▶ cancelled
```

- **People:** a task is `offered` unless it is set to auto-start *and* the person allows auto-start (`dispatch_mode=auto`).
  Work from an untrusted trigger (webhook, Slack) for a person is always `offered`, whatever the workflow says. Accepting queues it as interactive (a terminal opens) or headless.
- **AI developers:** tasks are `queued` immediately; a runner in the right pool claims them.
- A session reports `FLOCKIT_TASK_ID` (laptops) or uses its task-scoped token (runners); ingest links it to the task and
  moves the task to `running`. Headless runs finish when the agent or runner reports; interactive tasks finish when the
  person's session ends, or when they mark it done.
- The sweeper fails tasks a machine claimed but never started (20 minutes) or whose machine stopped reporting (30 minutes).

## CLI (`collector/`, package `flockit`, Python 3.9+, standard library only)

| Module | Responsibility |
|---|---|
| `hook.py` | Claude Code hook: builds redacted metadata events; on Stop/SessionEnd reads the new part of the transcript |
| `redact.py` | The metadata allowlist and the credential scrubber |
| `conversation.py` | Transcript and stream-json entries → redacted messages, token usage (deduplicated per API message), files touched; path rewriting |
| `outbox.py`, `transport.py` | Local buffer; delivery in a detached process; deletes only acknowledged events |
| `agent.py` | `flockit agent`: long-poll, notifications, run tasks (terminal or headless with a tool allowlist) |
| `workspace.py` | Finds the developer's checkout (learned locally from their sessions) or clones it; creates a git worktree per task |
| `launch.py` | Start script (everything quoted; the prompt is read from a file) and terminal launching; desktop notifications |
| `service.py` | launchd / systemd user service |
| `runner.py` | `flockit runner`: Docker (or local) sandboxes, Claude Code or Codex headless, live transcript streaming, push, PR |
| `workbench.py` | The services an AI developer works against: a private network, one container per service, volumes kept between tasks, a seed script that runs once |
| `notify.py` | Posting a finished task back to the Slack thread it came from — from the runner, so the server stays zero-egress |
| `mcp.py` | `flockit mcp`: the org's sessions over MCP (stdio JSON-RPC), scoped by the API to whatever its owner may see |

## Data model

| Table | Notes |
|---|---|
| `organization`, `user`, `team`, `team_member` | `user.kind` is `human` or `ai`. AI developers carry vendor, model, runner pool, sponsor and standing instructions. `user.dispatch_mode` is a person's consent setting |
| `login_session`, `api_token` | Hashes only. `api_token.run_id` and `expires_at` make per-task tokens for AI developers |
| `session` | Required `human_owner_id`, optional `actor_id`, `workflow_run_id`, title, token counters, tool calls, files touched |
| `session_message` | One row per prompt, reply, tool call or tool result; generated `tsvector` column with a GIN index |
| `session_file` | Files edited per session |
| `workflow` | Prompt template, repo, assignee, mode, permission profile, cron + time zone, webhook (hashed secret, JSON filter) |
| `workflow_run` | A task. Status, trigger and payload, branch, machine, linked session, result, error, PR, cost |
| `machine` | Laptops (per person) and runners (with hashed runner token, pool, capacity, capabilities) |
| `audit_event` | Who dispatched what to whom, and changes to AI developers, runners, workflows and consent |
| `fact`, `decision`, `retrieval` | Schema only, for the memory milestones |

## Web (`web/`)

React 19, TypeScript, TanStack Query (polling; no websockets), Tailwind 4, React Router 7. No component library. Every asset,
fonts included, is bundled and served by the Flockit server, and the Content-Security-Policy forbids other origins. Filters,
selections and open drawers live in the URL.
