# Workbenches

*The services an AI developer works against, kept between tasks.*

## Why this exists

A developer's machine has a database with real-shaped data in it. It survives reboots. It holds the schema they
migrated last week. It is the reason they can say "I ran it" before asking for a review.

An agent without one can only write code that looks right. It cannot run the migration it just wrote, cannot see the
query plan, cannot watch its own change fail against a row that has a null where it did not expect one. Every mistake
it makes travels downstream to a human reviewer, which is exactly the work you were trying to save.

So Flockit gives each AI developer a **workbench**: a private Docker network with a few services on it, started next
to the sandbox and **not** thrown away afterwards.

```
flockit-env-<id>             the network, shared by every task for this workbench
flockit-env-<id>-db          one container per service, reused between tasks
flockit-env-<id>-db-data     its volume — where the data actually lives
flockit-env-<id>-state       a marker: the setup script has run and succeeded
```

The sandbox that runs the agent is destroyed after every task. The workbench is not. That asymmetry is the whole
design: **throwaway compute, persistent context.**

## What a workbench is made of

| Field | Meaning |
|---|---|
| `services` | Containers started beside the agent. Each has a `name` (its hostname on the network), an `image`, `env`, a `port`, and optionally `data_path` — the directory kept in a volume. |
| `url_env` / `url` | The variable the agent reads to reach the service, and its value. `DATABASE_URL=postgresql://app:flockit@db:5432/app`. |
| `ready` | A command run inside the service until it succeeds (`pg_isready -U app`), so the agent never starts against a database that is still booting. |
| `variables` | Plain environment variables for the agent. `CUSTOMER=northwind`, `PLAN=enterprise`. Not for secrets. |
| `secret_names` | **Names only.** The runner passes these through from its own environment. Flockit never stores the values. |
| `setup_script` | Runs **once**, the first time: migrations, fixtures, one customer's data. |
| `persistent` | Keep the services and their data between tasks (the default), or throw them away each time. |

Create one in the UI (**AI developers → Workbenches**), starting from a preset, then assign it to an AI developer.

## The setup script runs once — and only once it has worked

The first task on a new workbench runs `setup_script` inside the sandbox, before the agent starts, with the services
already up and `DATABASE_URL` set. Point it at your real schema:

```bash
psql "$DATABASE_URL" -f db/schema.sql
psql "$DATABASE_URL" -f db/seed.sql
```

It is recorded as done only when it **exits zero**. A seed that failed is retried on the next task, because a
half-built database is worse than an empty one — the agent would spend its run confused by data that is not there. If
it fails, the task's result says so instead of quietly producing a change nobody can trust.

## The pattern worth copying: one workbench per customer

The strongest use of this is not "a database for the API". It is:

> **Give an AI developer a workbench shaped like one customer's account, and give it that customer's tickets.**

Their plan, their volumes, the currency and timezone edge cases their data keeps hitting. When their bug arrives, the
agent reproduces it against data that behaves like theirs rather than a fixture that never fails — and the fix it
writes is tested against the thing that broke.

Over a few weeks the AI developer's page fills in: the repositories it has worked in, the parts of the codebase it has
edited, its record of merged work. That is how a lead decides who gets the next job — the same way they would for a
person who "knows the billing side".

Use anonymised data. A workbench is a development environment, not a production replica, and Flockit is not a safe
place to put customer records.

## What the agent sees

Inside the sandbox, the workbench is just environment variables and hostnames:

```bash
$DATABASE_URL     # postgresql://app:flockit@db:5432/app
$REDIS_URL        # redis://cache:6379/0
$CUSTOMER         # northwind
$FLOCKIT_WORKBENCH # the workbench's name
```

`db` and `cache` resolve on the private network. Nothing else is reachable: the sandbox has no route to your other
services, and the workbench has no published ports.

## Safety

Everything in a workbench declaration ends up on a `docker run` command line, so it is validated twice — when it is
saved (`routers/environments.py`) and again on the runner before anything is started (`collector/src/flockit/
workbench.py`). Image names must look like image names, variable names must look like variable names, values may not
contain line breaks, data paths must be absolute. A service that does not pass is dropped with a line in the log, not
passed to Docker and hoped for.

Sandboxes get memory, CPU and PID limits. Services get their own. Neither holds a git credential: the runner clones
and pushes outside the sandbox.

## Managing them on a runner

```bash
flockit workbench list          # what is running on this machine
flockit workbench rm <env-id>   # remove one, data included
```

Removing a workbench in the UI removes the declaration. The containers and volumes live on the runners, so clean those
up with `flockit workbench rm` on the runner itself — deliberately manual, because it deletes data.

## When you do not need one

Repositories whose tests run with nothing else (a library, a CLI, a static site) do fine with the **No services**
preset: the agent gets the variables and nothing more. You can always add a database later; the AI developer does not
change.
