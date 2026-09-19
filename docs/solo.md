# Flockit for one developer

You do not have an engineering organisation. You have a laptop, a few repositories, and Claude Code open most of
the day. Flockit is still worth twenty minutes, for three reasons:

- **Your own work becomes searchable.** Every session you run is kept — the prompts, the commands, the files. In six
  weeks, when you hit the same error, `search_sessions` finds what you did the first time.
- **Your editor gets that memory.** Claude Code can query Flockit through MCP, so the answer to *"have I solved this
  before?"* comes from your own history instead of a guess.
- **You get a second pair of hands.** An AI developer takes a task, works in a sandbox with its own database, runs your
  tests, and comes back with a branch. You review a diff instead of babysitting a terminal.

Everything runs on your machine. Nothing is sent anywhere except the model provider you already use.

## 1. Run it

```bash
git clone https://github.com/giladlevy1/flockit.git
cd flockit
docker compose up -d
```

Open <http://localhost:8080>, create your organisation (it is just you), and pick a password.

## 2. Connect your laptop

**Connect** shows a one-line command with your token in it:

```bash
curl -fsSL http://localhost:8080/install.sh | sh -s -- flk_your_token
```

That installs the collector (Claude Code hooks) and the background agent. Run `claude` anywhere and the session shows
up in Flockit within seconds, with the repo, branch, model and the whole conversation.

Nothing about your machine leaves it: credentials are stripped and paths are rewritten before anything is sent, and
the only address the collector talks to is your own server. See [what is captured](../SECURITY.md).

## 3. Give your editor the memory

On **Connect**, create an **editor token**, then:

```bash
~/.flockit/venv/bin/flockit mcp install --token flk_your_editor_token
```

Now, inside any Claude Code session:

> *"Search flockit for how I fixed the timezone bug in the invoice exporter."*
> *"What did I change in the auth service last week?"*

The full list of tools is in [docs/mcp.md](mcp.md). It reads only what you can see — which, for you, is everything you
have done.

## 4. Hire an AI developer

You need somewhere for it to run. On your own machine that is one command:

```bash
~/.flockit/venv/bin/flockit runner build-image        # Claude Code and Codex in a sandbox image
export ANTHROPIC_API_KEY=...                          # or CLAUDE_CODE_OAUTH_TOKEN, from `claude setup-token`
export GH_TOKEN=...                                   # to push branches and open pull requests
~/.flockit/venv/bin/flockit runner --server http://localhost:8080 --token frn_...
```

Create the runner token in the UI first (**AI developers → Add runner**). Leave that command running in a terminal;
it is the only part of Flockit that talks to the outside world.

Then **Hire an AI developer**: give it a name, your repository, and a workbench (start with *Web service with
Postgres*). Assign it a real ticket — something you have been putting off — and watch it work in the session view.

## 5. Let it prove its own work

The workbench is the part that matters, and the part most tools skip. Your AI developer gets a Postgres database that
**survives between tasks**, exactly like the one on your laptop: it can run your migrations, seed it, query it, and run
the tests against it. An agent that can run the thing it just changed catches its own mistakes; one that cannot is
guessing, and you become its test suite.

Point the setup script at your schema when you create the workbench:

```bash
psql "$DATABASE_URL" -f db/schema.sql && psql "$DATABASE_URL" -f db/seed.sql
```

More in [docs/workbenches.md](workbenches.md).

## What it costs to run

The server and database idle at well under 300 MB. Sessions are text; a busy month is a few hundred megabytes. Model
spend is whatever your AI developers use, shown per task and per agent in the UI.

## When you are ready for other people

Move the compose file to a machine your team can reach, set `FLOCKIT_PUBLIC_URL`, and read [docs/team.md](team.md).
Nothing about your setup changes — your sessions and history come with you.
