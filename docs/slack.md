# Slack

*Start work where the complaint arrives, and get the answer back in the same thread.*

```
/flockit ada the checkout webhook retries forever on 429, have a look
→ 🤖 Ada picked up "the checkout webhook retries forever on 429" in github.com/acme/api. I'll post the result here.
→ ✅ Ada — the checkout webhook retries forever on 429
   The retry loop ignored Retry-After… Pull request: https://github.com/acme/api/pull/812
```

## How it stays zero-egress

Flockit's server makes no outbound calls, and this feature does not change that:

- **Inbound**: Slack POSTs to your Flockit. The slash command is answered *in the reply to Slack's own request* — no
  callback needed.
- **Outbound**: the result is posted by the **runner** that did the work, using its own bot token. Runners already
  reach the model provider and your git host; Slack is one more.

So your Flockit server still never opens a connection to the internet. If you do not set `SLACK_BOT_TOKEN` on the
runner, everything still works — the result is in Flockit, it is just not announced.

## 1. Create the Slack app

Slack → **Your apps** → **Create New App** → **From scratch**. Then:

**Slash Commands** → Create:
- Command: `/flockit`
- Request URL: `https://flockit.internal.example.com/api/slack/command`
- Description: "Give work to an AI developer"

**OAuth & Permissions** → Bot Token Scopes: `commands`, `chat:write`. Install to the workspace and copy the **Bot User
OAuth Token** (`xoxb-…`).

**Basic Information** → copy the **Signing Secret**.

Optional, for `@flockit …` in channels: **Event Subscriptions** → Request URL
`https://flockit.internal.example.com/api/slack/events`, subscribe to `app_mention`, and add the `app_mentions:read`
scope. Slack verifies the URL immediately, so set the signing secret first.

Your Flockit must be reachable from Slack. If it is not exposed to the internet, this feature is not for you — that is
a reasonable trade, and everything else in Flockit works without it.

## 2. Configure the two sides

On the **server** (`.env`, then `docker compose up -d`):

```bash
FLOCKIT_SLACK_SIGNING_SECRET=<the signing secret>
```

On each **runner**:

```bash
export SLACK_BOT_TOKEN=xoxb-…
```

Without the signing secret the Slack endpoints return 404 — the feature is off, not half on.

## 3. Everyone links their account, once

Flockit never calls Slack to look anyone up, so the link is made from the side that already knows who you are: open
**Connect → Slack**, copy the code, and paste it into any Slack channel.

```
/flockit link 7A85CTDR
→ Linked to Maya Cohen. Try /flockit <ai developer> <what to do>.
```

Codes expire in 15 minutes, are stored only as a hash, and grant nothing on their own — they associate a Slack user id
with a Flockit account and nothing else. Unlink from the same place.

## What you can type

| | |
|---|---|
| `/flockit ada fix the flaky checkout test` | Give Ada a task, in its usual repository |
| `/flockit ada repo=github.com/acme/web fix …` | Somewhere else |
| `/flockit tasks` | What you have running |
| `/flockit link <code>` | Connect this Slack account |
| `/flockit help` | The above |
| `@flockit ada …` | The same, as a channel mention (needs Event Subscriptions) |

## The safety rules

Slack text is written by whoever can type in a channel, which makes it the same category of input as a webhook:

- **Slack-triggered work never auto-starts on a person's laptop.** If a task from Slack is aimed at a person, it waits
  in their inbox for them to accept — whatever their auto-start setting says. AI developers still run immediately,
  because a sandbox is the right place for text someone else wrote.
- **The prompt carries a warning.** Work from Slack or a webhook reaches the agent with an explicit instruction to
  treat that text as information about a problem, not as instructions to follow.
- **Every request is verified.** Slack signs each one; Flockit checks the signature and rejects anything unsigned,
  mismatched, or more than five minutes old. The endpoint is public, so that signature is the only door.
- **You can only assign work you could assign in the UI.** The same role scoping applies, and repositories are still
  checked against `FLOCKIT_ALLOWED_GIT_HOSTS`.

## Troubleshooting

- *`dispatch_failed` in Slack* — Flockit was not reachable, or took longer than 3 seconds. Check the URL and that the
  server is up.
- *"This Slack account is not linked"* — do step 3.
- *No result posted back* — the runner has no `SLACK_BOT_TOKEN`, or the bot is not in that channel. Invite it with
  `/invite @flockit`.
- *Everything returns 404* — `FLOCKIT_SLACK_SIGNING_SECRET` is not set on the server.
