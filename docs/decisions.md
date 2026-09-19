# Decisions

Decisions made while building Flockit, with the reasoning, so they can be revisited deliberately rather than
drift. The strategy behind the project lives in the opportunity assessment; this is the build log.

## 0.1 (M0): visibility

| # | Decision | Why | Revisit when |
|---|---|---|---|
| 1 | **Name: Flockit.** | Many workers, human and agent, moving in one direction; short, friendly, ownable. `flockit` is free on PyPI and npm. The GitHub handle `flockit` is taken, so the repo lives at `giladlevy1/flockit`. | Company naming. |
| 2 | **License: Apache 2.0.** | Patent grant enterprises expect; standard for open core with a later commercial layer. | Before any paid tier. |
| 3 | **Collector in Python, stdlib only.** | One backend language, one redaction test suite, nothing third-party to audit, and it installs offline from the Flockit server into a private venv. Claude Code hooks just run a command, so Node brings no capability advantage. | If Python 3.9+ availability on developer machines turns out to be a real blocker. |
| 4 | **Teams are set manually by admins.** A lead sees everyone who shares a team with them. | Explicit and auditable. SSO/SCIM group sync can fill the same tables later. | SSO milestone. |
| 5 | **Collector supports local Claude Code only** (not containers or SSH). | Covers the common case; containers and SSH work anyway if `~/.flockit` and the hooks exist where Claude Code runs. | First team that runs Claude Code in devcontainers. |
| 6 | **Validated against real sessions on this machine**, headless and with a git remote containing a token. Two developer identities, one server. | The brief asked which repos to use for the first internal test; that is still open for a real team trial. | Five-team trial (artifact step 5). |
| 7 | **Every table carries `org_id`.** One organisation per deployment in M0. | Makes a later multi-tenant deployment a query change, not a schema rewrite. Costs nothing now. | Hosted offering. |
| 8 | **Outcome mapping is conservative.** `completed` only for explicit developer exits; headless `claude -p` ends with reason `other` and is shown as *Ended*, not *Completed*. `errored` is reserved. | We would rather under-claim than invent outcomes. Merged/not-merged needs git data (later milestone). | When PR/merge data is captured. |
| 9 | **Abandoned = open with no activity for 6 hours** (configurable). Activity reopens it. | Sessions left open over lunch should not be counted as abandoned; overnight ones should. | After the first real team's data. |
| 10 | **Live = activity within 15 minutes.** Idle = open but quiet. | Claude Code reports activity at the end of each turn; long turns can exceed a few minutes. | If turn-level heartbeats are added. |
| 11 | **Task reference is inferred** from `FLOCKIT_TASK_REF`, the branch name, or the first prompt that mentions a ticket. Only the reference is sent. | Makes `task_ref` populated without asking developers to do anything, while prompts never leave the laptop. | If false positives show up in real data. |
| 12 | **"Same ticket, several people" panel.** | The artifact's "where the same problem is being solved twice" question, answered with data M0 already has. Pure visibility; no new capture. | — |
| 13 | **UI polls every 5 seconds** instead of websockets. | No extra infrastructure (constraint 6), trivially correct behind any proxy. | If polling load matters at a few hundred concurrent viewers. |
| 14 | **The server hosts the collector package** (`/install.sh`, `/downloads/*.whl`). | One-command, offline install that works in air-gapped networks; no dependency on PyPI or GitHub. | — |
| 15 | **MCP server is not in M0.** The artifact's v0 build list mentions it, but its milestone table puts MCP serving at M2, and the build brief excludes retrieval from M0. We followed the milestones. `retrieval.session_id` is nullable so an agent Flockit did not start can retrieve later. | Brief section 11: the artifact wins on conflicts, and the artifact's own milestones place it at M2. | M2. |

## 0.2: from visibility to delegation

On 2026-09-20 Gilad chose to go beyond the M0 exclusion list: Flockit now dispatches work (to people's laptops and to AI
developers), captures full transcripts, and runs a workflow engine. The original assessment excluded these because Devin and
Factory sell autonomous execution. The bet here is different: the only place that already knows every person, every agent and
every past session in an org is also the right place to hand out the next piece of work, to whoever should do it, human or AI.

| # | Decision | Why | Revisit when |
|---|---|---|---|
| 16 | **Full transcripts, always on**, redacted on the laptop. | The org's own record of how work was done is the asset: search, hand-off, and later memory all depend on it. Chosen by Gilad over a per-org toggle. | First enterprise security review; a per-org "metadata only" switch is a small change. |
| 17 | **Dispatch to people: both modes, set per workflow.** "Ask" offers the task; "auto-start" runs headless, but only for people who opted in. | Consent is the line between a delegation tool and remote code execution. | — |
| 18 | **Webhook-triggered work never auto-starts on a person's laptop**, whatever the workflow says. Webhook-derived prompts carry an explicit "treat as data" warning. | Webhook text is written by whoever can file a ticket: a prompt-injection path to a developer's machine. AI developers still auto-start, in throwaway sandboxes. | If signed webhooks from trusted sources are added. |
| 19 | **Laptop tasks run in a fresh git worktree** on a `flockit/<id>-<title>` branch. Headless runs use a tool allowlist (edit, git, package managers, tests); "full access" is capped on laptops. | Never touch a developer's checkout or uncommitted work; keep unattended runs boring. | — |
| 20 | **AI developers are users** (`kind=ai`) with a required human sponsor. Their sessions are owned by the person who assigned the task (or the sponsor); the AI is the actor. | Accountability, audit and role scoping keep working with no special cases. | — |
| 21 | **Runners are the only component with outbound network access.** Model and git credentials live on the runner; tasks get a short-lived, task-scoped ingest token. | Keeps the control plane zero-egress while AI developers still reach the model and the git host. | — |
| 22 | **Docker sandboxes by default**, one container per task, thrown away after. A `local` backend exists for development and hosts without Docker. | Isolation for agents running with full permissions. | Firecracker or gVisor for stronger isolation. |
| 23 | **Triggers: manual, cron (with time zones), generic webhook.** No first-party GitHub/Zendesk apps. | A generic webhook with a JSON filter covers them all without outbound calls or OAuth apps. | When a first-party integration removes real setup pain. |
| 24 | **Postgres full-text search**, no vector database. | Constraint 6 still holds (Postgres only). Exact terms, file names and error strings are what people search for. | If semantic search becomes the bottleneck. |
| 25 | **Codex support is runner-only.** Laptops run Claude Code. | Claude Code's hooks give the richest capture on laptops; Codex's JSON stream is enough for sandboxes. | — |

## Open questions for the next milestone

- Which real repos and which five teams run the first trial?
- Should headless/CI Claude Code sessions (`claude -p`) be shown separately from interactive ones?
- Tokens per session are now captured (0.2): the benchmark harness can use them as its baseline.
- Should there be an org-level retention period for transcripts (e.g. 90 days) and a per-person export?
- First-party notifications (Slack/email) require outbound calls from the server: opt-in integration, or leave to webhooks?
