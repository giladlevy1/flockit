# flockit (CLI)

The per-machine half of [Flockit](https://github.com/giladlevy1/flockit): one zero-dependency Python package with three
jobs.

| Command | Where it runs | What it does |
|---|---|---|
| `flockit hook` | every developer machine (registered as a Claude Code hook) | reports sessions and their redacted transcripts to **your** Flockit server |
| `flockit agent` | every developer machine (launchd / systemd user service) | notifies you of tasks; opens Claude Code in a fresh git worktree when you accept one; runs auto-start tasks headless |
| `flockit runner` | a Docker host in your network | runs AI-developer tasks in sandboxes (Claude Code or Codex), streams the session, pushes the branch, opens a PR |

```bash
flockit install --server http://flockit.internal:8080 --token flk_...   # hooks + agent
flockit status
flockit tasks                      # what is waiting for you
flockit tasks accept <id>          # or --headless
flockit agent stop | start | status
flockit runner build-image
flockit runner --server http://flockit.internal:8080 --token frn_... [--backend docker|local] [--capacity 2]
flockit uninstall
```

The easiest install is the one-line command on your server's **Connect** page, which installs this package from the server
itself, with no internet access needed.

## Redaction

Everything is redacted on the machine before it is sent (see `src/flockit/redact.py` and `src/flockit/conversation.py`):
credentials (API keys, tokens, private keys, connection strings, secret-named assignments, high-entropy blobs) are replaced
with `[REDACTED]`, and absolute paths are rewritten relative to the repository or to `~`.
