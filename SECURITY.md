# Security policy

Flockit runs inside your network and handles metadata about your engineering work, so we take reports
seriously.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting on this repository
(Security → Report a vulnerability). We aim to acknowledge reports within three working days.

Especially valuable:

- any way for the collector to transmit a prompt, transcript, file path, environment variable or
  credential (see `collector/src/flockit/redact.py`);
- any way for a user to see sessions or people outside their role's scope;
- any outbound network call from the server, the UI or the collector.

## Design notes for reviewers

- Redaction runs on the developer's machine, before transmission. The server never receives raw hook
  input.
- Passwords are Argon2 hashes. Login cookies and collector tokens are stored as SHA-256 hashes only.
- Mutating API requests require the `X-Flockit-Request` header (CSRF protection); the server sends no
  CORS headers.
- Postgres is not published outside the compose network.
- The server sets a strict Content-Security-Policy; the UI loads nothing from other origins.
