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
- AI developers run on runners, in a new Docker container per task. Model and git credentials live only on the
  runner. Each task gets an ingest token scoped to that task, revoked when it ends.
- Passwords are Argon2 hashes. Login cookies and collector tokens are stored as SHA-256 hashes only.
- Mutating API requests require the `X-Flockit-Request` header (CSRF protection); the server sends no
  CORS headers.
- Postgres is not published outside the compose network.
- The server sets a strict Content-Security-Policy; the UI loads nothing from other origins.
