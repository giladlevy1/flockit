# Flockit in your editor (MCP)

*Your org's coding history, available to the session you are in right now.*

Flockit captures every Claude Code session. This is the part that makes that worth something: an MCP server on your
machine that lets the agent you are talking to search that history, read a specific session, and hand work to an AI
developer — without you leaving the terminal.

```
you → claude code → flockit mcp (stdio, on your machine) → your Flockit server
```

## Install

1. In Flockit, open **Connect** and create an **editor token**. It is shown once.
2. Run:

```bash
~/.flockit/venv/bin/flockit mcp install --token flk_your_editor_token
```

That registers the server with Claude Code (`claude mcp add --scope user`). For another MCP client, print the
configuration instead:

```bash
flockit mcp install --print-only
```

```json
{ "mcpServers": { "flockit": { "command": "/Users/you/.flockit/venv/bin/flockit", "args": ["mcp", "serve"] } } }
```

## What you can ask

Once it is installed, this is ordinary conversation:

> *"Search flockit for the checkout race condition — has anyone fixed this before?"*
> *"Read session 2edb107b and tell me what they tried that did not work."*
> *"What has Ada been working on in the api-gateway this week?"*
> *"Hand this to Ada: reproduce the 500 on invoice export for large accounts, then fix it."*

## The tools

| Tool | What it does |
|---|---|
| `search_sessions` | Full-text search across every session you are allowed to see: prompts, replies, commands, file names. |
| `get_session` | One session end to end — the conversation, the tool calls, the files it touched. |
| `recent_sessions` | The latest sessions, optionally filtered by repository or person. |
| `ai_developers` | The org's AI developers: what each is working on, its workbench, its repository. |
| `ai_developer` | One of them in detail: workbench, the repositories and areas it knows, recent tasks. |
| `my_tasks` | What is assigned to you. |
| `assign_task` | Give work to an AI developer. It runs in a sandbox and reports back in Flockit. |

## Scope, and why it cannot be widened

An editor token **acts as you**. A developer sees their own sessions; a lead sees their teams'; an admin sees the
organisation. The MCP server does not enforce that — the API does, with the same queries that serve the web UI, so
there is no second code path that could drift.

Two token kinds exist, and they cannot do each other's jobs:

| | writes sessions | reads Flockit |
|---|---|---|
| **collector token** (on every machine that runs the collector) | yes | **no** |
| **editor token** (opt-in, created by you) | **no** | yes, within your role |

That separation is deliberate: a collector token sits in a config file on every laptop, so it must not be a key to the
organisation's transcripts. If an editor token leaks, revoke it on **Connect**; it stops working immediately.

## Privacy

The MCP server runs on your machine and talks only to your Flockit server — the same single destination the collector
uses. It sends no telemetry, and what it returns has already been through redaction on the machine that produced it.

If your organisation would rather nobody read anyone else's sessions from an editor, simply do not create editor
tokens: the feature is off until someone opts in, per person.

## Troubleshooting

```bash
flockit mcp serve < /dev/null    # should exit silently; errors print to stderr
```

- *"No editor token yet"* — create one on **Connect** and rerun `flockit mcp install --token …`.
- *"The editor token was rejected"* — it was revoked, or belongs to a different server. Create a new one.
- Claude Code does not list the server — check `claude mcp list`, and that the path in the configuration is the
  absolute path to your `flockit` binary (`~/.flockit/venv/bin/flockit`).
