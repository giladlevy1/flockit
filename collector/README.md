# flockit (collector)

The per-developer half of [Flockit](https://github.com/giladlevy1/flockit). It registers
itself as a Claude Code hook, reports session metadata to **your own** Flockit server, and
redacts locally before anything leaves your machine.

```bash
flockit install --server http://flockit.internal:8080 --token flk_...
flockit status
flockit uninstall
```

The easiest way to install is the one-line command on your server's **Connect** page,
which installs this package from the server itself, so no internet access is needed.

## What is sent

Only these fields, after validation and secret scrubbing (see `src/flockit/redact.py`):

| Field | Example |
|---|---|
| session id | Claude Code's session UUID |
| agent vendor, version, model | `claude-code`, `2.1.3`, `claude-opus-5` |
| repo | `github.com/acme/api` (credentials and local paths stripped) |
| branch | `feature/ENG-123-login` |
| task ref | `ENG-123`, `#42`, or an issue URL without its query string |
| start source / end reason | `startup`, `prompt_input_exit` |

Never sent: prompts, responses, transcripts, file contents, command output, file paths,
environment variables.
