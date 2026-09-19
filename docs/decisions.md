# M0 decisions

Decisions made while building M0, with the reasoning, so they can be revisited deliberately rather than
drift. The strategy behind the project lives in the opportunity assessment; this is the build log.

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

## Open questions for the next milestone

- Which real repos and which five teams run the first trial?
- Should headless/CI Claude Code sessions (`claude -p`) be shown separately from interactive ones?
- Is "tokens per session" worth capturing in M1 as the baseline for the benchmark harness? It would
  come from the transcript's usage metadata (numbers only, no content).
