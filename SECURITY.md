# Security policy

Flockit runs inside your network and handles metadata about your engineering work, so we take reports
seriously.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting on this repository
(Security → Report a vulnerability). We aim to acknowledge reports within three working days.

Especially valuable:

- any credential, absolute path or username that survives redaction (`collector/src/flockit/redact.py`,
  `conversation.py`) and reaches the server;
- any way for a user to see sessions, transcripts, search results, tasks or people outside their role's scope;
- any way to start work on someone's machine without their consent (they did not accept the task, and did not
  allow auto-start), or to make a webhook-triggered task auto-start on a laptop;
- any way for a runner token or a per-task token to act on tasks it did not claim;
- shell or argument injection through task titles, prompts, repos or branches;
- any outbound network call from the server or the UI.

## Design notes for reviewers

- Redaction runs on the developer's machine, before transmission. The server never receives raw hook
  input. Transcripts are captured in full after redaction; paths are rewritten relative to the repository.
- Tasks for people start only after they accept, unless they opted into auto-start. Webhook-triggered work
  never auto-starts on a laptop. Laptop runs happen in a new git worktree with a tool allowlist.
- AI developers run on runners, in a new Docker container per task. **No git credentials ever enter a sandbox**: the
  runner clones and pushes; the container only edits and commits locally. The git token is sent only to hosts on the
  allowlist (`FLOCKIT_ALLOWED_GIT_HOSTS`), so a task cannot make a runner authenticate to an attacker's server.
- Repository names and branches are validated when a task is created (host/owner/name on an allowed host; no `..`, no
  option-looking values, no URLs), and again on the runner before any git command.
- Each task gets an ingest token scoped to that task. It may only send that session's transcript: it is rejected by the
  agent and runner APIs, and stops working the moment the task reaches a final state (including cancel and decline).
- Webhook deliveries are rate-limited and size-capped per workflow, so a leaked webhook URL cannot run up a model bill.
- Passwords are Argon2 hashes. Login cookies and collector tokens are stored as SHA-256 hashes only.
- Mutating API requests require the `X-Flockit-Request` header (CSRF protection); the server sends no
  CORS headers.
- Postgres is not published outside the compose network.
- The server sets a strict Content-Security-Policy; the UI loads nothing from other origins.
