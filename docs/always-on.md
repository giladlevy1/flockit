# Always-on sessions

*Close your laptop mid-task. The work carries on.*

## What happens today, without this

You are twenty minutes into a session. The agent has reproduced the bug, changed two
files, and is running the tests. You close the lid to catch a train.

Claude Code does not end — it is suspended. No Stop hook, no result, no summary. The next
morning you reopen a terminal to a frozen conversation, a working tree you have to
remember the state of, and an agent that was about to do something you can no longer see.
That is the most common way an agent session dies, and it is pure waste: the context was
expensive to build and it evaporates on a lid.

## What happens with it on

Two things Flockit already knows, put together:

1. **While you work**, the agent on your machine snapshots your working tree once a minute
   and pushes it to a shadow ref — uncommitted changes, new files, deletions and all.
2. **When your machine stops reporting** mid-session, the work is handed to *your* AI
   developer, which starts from that snapshot with the conversation so far as context.

You get a notification-free handover: the interrupted session closes with "continued", the
new session links to it, and when you open Flockit you see what your agent did while you
were on the train. If you want it back, **Continue** on the session brings it to your
machine with `claude --resume` in the same checkout.

```
 laptop                              Flockit                        runner
 ──────                              ───────                        ──────
 session live ──snapshot─▶  refs/flockit/wip/<session>
 …lid closes…
 (agent stops reporting) ─────────▶  machine quiet + session open
                                     └─▶ task for "your agent" ────▶ clone, restore tree,
                                                                      continue, push branch
```

## Turning it on

**Connect → Always-on sessions → Turn it on.** That creates one AI developer that belongs
to you: it only ever continues your sessions, it is sponsored by you, and everything it
does is recorded like any other session.

You also need a runner — a machine with Docker where the work can actually continue
(see [team.md](team.md) or [solo.md](solo.md)).

## What is sent, and what is not

The snapshot is a git commit on a ref outside `refs/heads`, pushed to **your own
repository** with **your own git credentials**. It does not go to Flockit; Flockit only
records the ref name and the commit id.

- `.gitignore` is respected, so `.env`, build output and `node_modules` stay on your machine.
- It is a snapshot, not a history: each one replaces the last.
- It never appears as a branch, so it does not clutter your branch list and does not
  trigger CI.
- If your repository has no remote, or you cannot push, the snapshot stays local and the
  session simply is not continuable — Flockit knows, and will not hand it anywhere.

## What it will not do

Every one of these is a reason to *refuse* a handover, and all of them must pass:

| | |
|---|---|
| **You asked for it** | Off until you turn it on, per person. |
| **Your machine is actually gone** | Every machine of yours must have stopped reporting. Thinking with your laptop open is the most common way to look idle; that is not an interruption. |
| **There is something to continue** | A pushed snapshot and a repository, or nothing happens. |
| **It is still today's work** | A session quiet for more than 45 minutes is not interrupted, it is over. |
| **One at a time** | Your agent finishes what it has before taking another handover, so a flapping connection cannot start three agents on one repository. |
| **Once** | A session is handed over at most once. |

## How the snapshot avoids touching your work

This runs every minute on a developer's machine, so it uses git plumbing that cannot
disturb what they are doing:

```
GIT_INDEX_FILE=<temp>  git read-tree HEAD     # a throwaway index, not yours
GIT_INDEX_FILE=<temp>  git add -A             # your staged changes are never read or written
                       git write-tree
                       git commit-tree <tree> -p HEAD
                       git update-ref refs/flockit/wip/<session> <commit>
                       git push --force origin <commit>:refs/flockit/wip/<session>
```

Your index, HEAD, branches and stash are untouched, and `git status` looks exactly the same
before and after. The tests for this assert precisely that, because it is the property that
makes the feature safe to leave on.

On the other side, the runner restores with `git read-tree -u --reset <snapshot>` on top of
the task branch, so a file you deleted is deleted there too — the tree the agent sees is
the tree you left.

## Costs

Each handover is one agent run on your runner, with its own model cost, shown on the task
and on your agent's page like any other work. If that is not what you want on a given day,
turn it off — it is a switch, not a policy.
