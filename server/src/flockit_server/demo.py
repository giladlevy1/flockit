"""Demo organisation for evaluating Flockit without installing a collector.

Everything here is fictional. Loaded only by ``flockit-server seed-demo`` into an
empty database, never automatically.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from flockit_server import db
from flockit_server.models import (
    AgentSession,
    AuditEvent,
    DispatchMode,
    Machine,
    Organization,
    Origin,
    Outcome,
    PermissionProfile,
    Role,
    RunMode,
    RunStatus,
    SessionFile,
    SessionMessage,
    Team,
    User,
    UserKind,
    Workflow,
    WorkflowRun,
)
from flockit_server.security import hash_password, hash_token

DEMO_PASSWORD = "flockit-demo"

PEOPLE = [
    # name, email, role, teams
    ("Maya Cohen", "maya@acme.dev", Role.admin, ["Platform"]),
    ("Daniel Park", "daniel@acme.dev", Role.lead, ["Platform"]),
    ("Noa Levi", "noa@acme.dev", Role.developer, ["Platform"]),
    ("Sam Okafor", "sam@acme.dev", Role.developer, ["Platform"]),
    ("Priya Raman", "priya@acme.dev", Role.lead, ["Payments"]),
    ("Tom Becker", "tom@acme.dev", Role.developer, ["Payments"]),
    ("Lena Novak", "lena@acme.dev", Role.developer, ["Payments"]),
    ("Yuki Tanaka", "yuki@acme.dev", Role.lead, ["Mobile"]),
    ("Omar Haddad", "omar@acme.dev", Role.developer, ["Mobile"]),
    ("Ava Martin", "ava@acme.dev", Role.developer, ["Mobile", "Payments"]),
]

REPOS = {
    "Platform": ["github.com/acme/api-gateway", "github.com/acme/infra", "github.com/acme/auth-service"],
    "Payments": ["github.com/acme/billing", "github.com/acme/ledger", "github.com/acme/api-gateway"],
    "Mobile": ["github.com/acme/ios-app", "github.com/acme/android-app", "github.com/acme/mobile-bff"],
}

TICKETS = {
    "Platform": ["PLAT-412", "PLAT-418", "PLAT-420", "PLAT-431", "PLAT-433"],
    "Payments": ["PAY-88", "PAY-91", "PAY-97", "PAY-102"],
    "Mobile": ["MOB-230", "MOB-241", "MOB-244", "MOB-250"],
}

BRANCH_WORDS = [
    "rate-limits", "retry-backoff", "invoice-pdf", "oauth-refresh", "dark-mode", "push-tokens",
    "ledger-reconcile", "flaky-e2e", "upgrade-node", "k8s-probes", "idempotency-keys", "offline-sync",
]

MODELS = [
    ("claude-opus-5", 0.35),
    ("claude-sonnet-5", 0.45),
    ("claude-haiku-4-5", 0.12),
    ("claude-opus-4-8", 0.08),
]


PROMPTS = [
    "The {ticket} bug: {what}. Find the root cause and fix it with a regression test.",
    "Refactor the {area} module so it is easier to test. Keep behaviour identical.",
    "Why does {what}? Walk me through it before changing anything.",
    "Implement {ticket}: {what}. Follow the patterns in the existing handlers.",
]
WHATS = [
    "retries hammer the payment provider when it returns 429",
    "the invoice PDF renders totals without currency",
    "the login page flashes the wrong theme",
    "push tokens are not refreshed after reinstall",
    "the ledger reconcile job double counts refunds",
    "e2e tests time out on the checkout page",
]
AREAS = ["rate limiting", "invoice rendering", "session handling", "notifications", "reconciliation"]


def _usage(rng: random.Random, minutes: int) -> dict:
    turns = max(1, minutes // 3)
    return {
        "tokens_input": rng.randint(800, 3000) * turns,
        "tokens_output": rng.randint(300, 1200) * turns,
        "tokens_cache_read": rng.randint(8000, 30000) * turns,
        "tokens_cache_write": rng.randint(1000, 4000) * turns,
        "tool_calls": rng.randint(2, 7) * turns,
        "files_touched": rng.randint(0, 6),
    }


def _title(rng: random.Random, ticket: str | None) -> str:
    template = rng.choice(PROMPTS)
    return template.format(ticket=ticket or "open", what=rng.choice(WHATS), area=rng.choice(AREAS))[:200]


def _transcript(session: AgentSession, start: datetime, rng: random.Random, prompt: str, reply: str, files: list[str]) -> list:
    """A short, plausible conversation for the demo's most recent sessions."""
    t = start
    rows = []

    def add(role: str, kind: str, content: str, tool: str | None = None) -> None:
        nonlocal t
        t = t + timedelta(seconds=rng.randint(4, 40))
        rows.append(
            SessionMessage(session_id=session.id, entry_id=f"demo-{len(rows)}", seq=len(rows), role=role, kind=kind,
                           tool_name=tool, content=content, occurred_at=t)
        )

    add("user", "text", prompt)
    add("assistant", "text", "Let me look at how this is wired up first.")
    add("assistant", "tool_use", f"rg -n \"{files[0].split('/')[-1].split('.')[0]}\" src tests", "Bash")
    add("user", "tool_result", f"{files[0]}:42:    def handle(self, request):\n{files[0]}:88:        return self._retry(request)", "Bash")
    for f in files:
        add("assistant", "tool_use", f"{f}\n--- replace\nfor attempt in range(5):\n+++ with\nfor attempt in backoff(max_tries=5, base=0.5):", "Edit")
        add("user", "tool_result", "The file has been updated.", "Edit")
    add("assistant", "tool_use", "pytest tests -q -k retry", "Bash")
    add("user", "tool_result", "12 passed in 3.41s", "Bash")
    add("assistant", "text", reply)
    session.message_count = len(rows)
    return rows


def _pick_model(rng: random.Random) -> str:
    r, acc = rng.random(), 0.0
    for model, weight in MODELS:
        acc += weight
        if r <= acc:
            return model
    return MODELS[0][0]


async def seed(days: int = 14) -> int:
    rng = random.Random(7)
    now = datetime.now(timezone.utc)
    async with db.sessionmaker()() as session:
        if (await session.execute(select(func.count()).select_from(User))).scalar_one():
            print("seed-demo only runs on an empty database. Start from a fresh volume.")
            return 1
        org = Organization(name="Acme (demo)")
        session.add(org)
        await session.flush()

        teams = {name: Team(org_id=org.id, name=name) for name in REPOS}
        session.add_all(teams.values())
        pw = hash_password(DEMO_PASSWORD)
        users = []
        for name, email, role, team_names in PEOPLE:
            user = User(org_id=org.id, email=email, name=name, role=role, password_hash=pw)
            user.teams = [teams[t] for t in team_names]
            users.append((user, team_names))
        session.add_all(u for u, _ in users)
        await session.flush()

        rows = []
        for user, team_names in users:
            activity = 0.9 if user.role == Role.developer else 0.6
            for d in range(days, -1, -1):
                day = now - timedelta(days=d)
                if day.weekday() >= 5 and rng.random() > 0.15:
                    continue
                for _ in range(rng.choices([0, 1, 2, 3, 4], weights=[1 - activity, 3, 4, 2, 1])[0]):
                    team = rng.choice(team_names)
                    start = day.replace(hour=rng.randint(8, 18), minute=rng.randint(0, 59), second=0, microsecond=0)
                    if start > now:
                        continue
                    minutes = int(min(rng.lognormvariate(3.3, 0.8), 240))
                    ticket = rng.choice(TICKETS[team]) if rng.random() < 0.7 else None
                    branch = (
                        f"feature/{ticket}-{rng.choice(BRANCH_WORDS)}" if ticket else f"chore/{rng.choice(BRANCH_WORDS)}"
                    )
                    model = _pick_model(rng)
                    end = start + timedelta(minutes=max(minutes, 2))
                    outcome = rng.choices(
                        [Outcome.completed, Outcome.abandoned, Outcome.unknown], weights=[80, 14, 6]
                    )[0]
                    ended_at = end
                    if end > now:
                        ended_at, outcome = None, Outcome.unknown
                    rows.append(
                        AgentSession(
                            org_id=org.id,
                            human_owner_id=user.id,
                            external_id=str(uuid.UUID(int=rng.getrandbits(128))),
                            agent_vendor="claude-code",
                            agent_version=rng.choice(["2.1.3", "2.1.4", "2.2.0"]),
                            agent_model=model,
                            models_used=[model],
                            repo=rng.choice(REPOS[team]),
                            branch=branch,
                            task_ref=ticket,
                            started_at=start,
                            last_seen_at=min(end, now),
                            ended_at=ended_at,
                            outcome=outcome,
                            end_reason="prompt_input_exit" if outcome == Outcome.completed else (
                                "inactive" if outcome == Outcome.abandoned else "other"
                            ),
                            turn_count=max(1, minutes // 3 + rng.randint(0, 6)),
                            collector_version="0.2.0",
                            **_usage(rng, minutes),
                        )
                    )

        # A few sessions running right now, so the view is live.
        for user, team_names in rng.sample(users, 5):
            team = team_names[0]
            ticket = rng.choice(TICKETS[team])
            start = now - timedelta(minutes=rng.randint(4, 95))
            model = _pick_model(rng)
            rows.append(
                AgentSession(
                    org_id=org.id,
                    human_owner_id=user.id,
                    external_id=str(uuid.UUID(int=rng.getrandbits(128))),
                    agent_vendor="claude-code",
                    agent_version="2.2.0",
                    agent_model=model,
                    models_used=[model],
                    repo=REPOS[team][0],
                    branch=f"feature/{ticket}-{rng.choice(BRANCH_WORDS)}",
                    task_ref=ticket,
                    started_at=start,
                    last_seen_at=now - timedelta(seconds=rng.randint(5, 240)),
                    outcome=Outcome.unknown,
                    turn_count=rng.randint(3, 40),
                    collector_version="0.2.0",
                    **_usage(rng, 45),
                )
            )

        for row in rows:
            row.title = _title(rng, row.task_ref)
        session.add_all(rows)
        await session.flush()

        # Recent sessions get a full conversation, so search and the timeline have something to show.
        recent = sorted(rows, key=lambda r: r.started_at, reverse=True)[:25]
        for row in recent:
            files = rng.sample(["src/payments/retry.py", "src/payments/client.py", "tests/test_retry.py", "src/invoices/pdf.py",
                                "app/checkout/page.tsx", "src/ledger/reconcile.py"], 2)
            session.add_all(_transcript(row, row.started_at, rng, row.title or "Fix it", (
                "Done. The retry loop now uses exponential backoff with jitter and gives up after 5 attempts; "
                "429 responses honour `Retry-After`.\n\n1. Changed `" + files[0] + "`\n2. Added a regression test in `"
                + files[1] + "`\n\nAll 12 retry tests pass."), files))
            session.add_all([SessionFile(session_id=row.id, path=f, edits=rng.randint(1, 4)) for f in files])
            row.files_touched = len(files)

        await _seed_work(session, org, rng, now, {u.email: u for u, _ in users}, teams)
        await session.commit()
    await db.dispose()
    print(f"Loaded demo organisation: {len(PEOPLE)} people, 2 AI developers, 3 teams, {len(rows)} sessions, tasks and workflows.")
    print("Sign in as maya@acme.dev (admin), daniel@acme.dev (lead) or noa@acme.dev (developer).")
    print(f"Password for every demo account: {DEMO_PASSWORD}")
    return 0


async def _seed_work(session, org: Organization, rng: random.Random, now: datetime, people: dict, teams: dict) -> None:
    """AI developers, a runner, workflows and tasks in every state."""
    from flockit_server.routers.workflows import next_run

    maya, daniel, noa, priya = people["maya@acme.dev"], people["daniel@acme.dev"], people["noa@acme.dev"], people["priya@acme.dev"]
    ada = User(org_id=org.id, email="ada@agents.flockit.local", name="Ada", kind=UserKind.ai, role=Role.developer,
               dispatch_mode=DispatchMode.auto, agent_vendor="claude-code", agent_model="claude-opus-5", sponsor_id=maya.id,
               instructions="You are Ada, an AI developer at Acme. Write the test first. Keep PRs small. Never touch CI config.")
    linus = User(org_id=org.id, email="linus@agents.flockit.local", name="Linus", kind=UserKind.ai, role=Role.developer,
                 dispatch_mode=DispatchMode.auto, agent_vendor="codex", agent_model="gpt-5-codex", sponsor_id=daniel.id)
    ada.teams = [teams["Platform"], teams["Payments"]]
    linus.teams = [teams["Platform"]]
    session.add_all([ada, linus])
    runner = Machine(org_id=org.id, kind="runner", name="build-box-1", token_hash=hash_token("frn_demo_" + str(uuid.uuid4())),
                     token_prefix="frn_demo_1", platform="linux-x86_64", version="0.2.0", capacity=2, last_seen_at=now,
                     capabilities={"backend": "docker", "docker": True, "claude": True, "codex": True, "git_push": True})
    laptop = Machine(org_id=org.id, kind="laptop", name="noa-mbp", user_id=noa.id, platform="darwin-arm64", version="0.2.0",
                     last_seen_at=now, capabilities={"claude": True, "terminal": True})
    session.add_all([runner, laptop])
    await session.flush()

    triage = Workflow(org_id=org.id, name="Triage new bugs", description="Every GitHub issue labelled bug goes to Ada first.",
                      prompt_template="A bug was reported: {{payload.issue.title}}\n\n{{payload.issue.body}}\n\nReproduce it with a failing test, fix it, and open a PR.",
                      repo="github.com/acme/api-gateway", assignee_id=ada.id, mode=RunMode.auto,
                      permission_profile=PermissionProfile.edit, webhook_enabled=True,
                      webhook_secret_hash=hash_token("whk_demo_" + str(uuid.uuid4())),
                      webhook_filter={"path": "label.name", "equals": "bug"}, created_by_id=maya.id, last_run_at=now - timedelta(minutes=12))
    deps = Workflow(org_id=org.id, name="Weekly dependency upgrades", description="Minor and patch upgrades, one PR per service.",
                    prompt_template="Upgrade minor and patch dependency versions. Run the full test suite. Open one PR with a changelog summary.",
                    repo="github.com/acme/billing", assignee_id=linus.id, mode=RunMode.auto, permission_profile=PermissionProfile.edit,
                    schedule_cron="0 8 * * 1", schedule_timezone="Asia/Jerusalem", next_run_at=next_run("0 8 * * 1", "Asia/Jerusalem"),
                    created_by_id=daniel.id, last_run_at=now - timedelta(days=4))
    flaky = Workflow(org_id=org.id, name="Investigate a flaky test", description="Sent to whoever owns the area; they accept and work with Claude.",
                     prompt_template="The test {{payload.test}} is flaky on CI ({{payload.rate}} failure rate). Find the race and fix it.",
                     repo="github.com/acme/api-gateway", assignee_id=noa.id, mode=RunMode.ask, permission_profile=PermissionProfile.edit,
                     created_by_id=daniel.id, last_run_at=now - timedelta(minutes=6))
    session.add_all([triage, deps, flaky])
    await session.flush()

    def run(title, assignee, status, trigger, by, wf=None, ago=10, repo="github.com/acme/api-gateway", **extra):
        created = now - timedelta(minutes=ago)
        r = WorkflowRun(
            org_id=org.id, workflow_id=wf.id if wf else None, title=title, prompt=extra.pop("prompt", title), repo=repo,
            branch=f"flockit/{uuid.uuid4().hex[:8]}-" + "-".join(title.lower().split()[:5]).replace(":", ""),
            assignee_id=assignee.id, mode=wf.mode if wf else RunMode.ask, status=status, trigger=trigger,
            triggered_by_id=by.id if by else None, created_at=created, updated_at=created,
            machine_id=(runner.id if assignee.kind == UserKind.ai else laptop.id) if status not in (RunStatus.offered, RunStatus.queued) else None,
            started_at=created + timedelta(minutes=1) if status in (RunStatus.running, RunStatus.succeeded, RunStatus.failed) else None,
            ended_at=created + timedelta(minutes=rng.randint(6, 25)) if status in (RunStatus.succeeded, RunStatus.failed) else None,
            **extra,
        )
        session.add(r)
        audit.append(AuditEvent(org_id=org.id, actor_id=by.id if by else None, action="task.created", target_type="task",
                                target_id=str(r.id), detail={"title": title, "assignee": assignee.name, "trigger": trigger}, created_at=created))
        return r

    audit: list = []

    runs = [
        run("Flaky test: checkout.spec times out on CI", noa, RunStatus.offered, "manual", daniel, flaky, ago=6,
            prompt="The test checkout.spec.ts is flaky on CI (12% failure rate). Find the race and fix it."),
        run("Review the billing migration plan", maya, RunStatus.offered, "assigned", priya, ago=30, repo="github.com/acme/billing"),
        run("Triage new bugs: 500 on /invoices export", ada, RunStatus.running, "webhook", None, triage, ago=4,
            task_ref="https://github.com/acme/api-gateway/issues/481"),
        run("Weekly dependency upgrades", linus, RunStatus.succeeded, "schedule", None, deps, ago=60 * 24 * 4, repo="github.com/acme/billing",
            result="Upgraded 14 packages (minor and patch only). All 312 tests pass.\n\n- `axios` 1.7.9 → 1.8.2\n- `zod` 3.23.8 → 3.24.1\n- `vitest` 2.1.4 → 2.1.8\n\nNo breaking changes in changelogs.",
            pr_url="https://github.com/acme/billing/pull/233", cost_usd=1.84),
        run("Triage new bugs: retries hammer the provider on 429", ada, RunStatus.succeeded, "webhook", None, triage, ago=180,
            result="Root cause: the retry loop ignored `Retry-After` and retried immediately.\n\n1. Added exponential backoff with jitter\n2. Honour `Retry-After` on 429\n3. Regression test `test_retry_after_is_honoured`",
            pr_url="https://github.com/acme/api-gateway/pull/1207", cost_usd=2.31, task_ref="https://github.com/acme/api-gateway/issues/476"),
        run("Add idempotency keys to POST /payments", noa, RunStatus.succeeded, "assigned", daniel, ago=60 * 26, interactive=True,
            repo="github.com/acme/billing", result="Done in an interactive session."),
        run("Upgrade the Postgres driver to v3", linus, RunStatus.failed, "assigned", daniel, ago=60 * 30, repo="github.com/acme/ledger",
            error="Tests failed after the upgrade: 7 failures in ledger/reconcile (timestamp precision changed). Needs a human decision on rounding."),
        run("Document the webhook retry policy", ada, RunStatus.queued, "assigned", priya, ago=2, repo="github.com/acme/api-gateway"),
    ]
    await session.flush()
    session.add_all(sorted(audit, key=lambda e: e.created_at))  # the log reads in time order

    # Sessions for the AI developers' work, linked to their tasks
    for r in runs:
        if r.assignee_id not in (ada.id, linus.id) or r.status not in (RunStatus.running, RunStatus.succeeded, RunStatus.failed):
            continue
        agent = ada if r.assignee_id == ada.id else linus
        owner = next((p for p in people.values() if p.id == r.triggered_by_id), None) or (maya if agent is ada else daniel)
        start = r.started_at or now
        s = AgentSession(
            org_id=org.id, human_owner_id=owner.id, actor_id=agent.id, origin=Origin.workflow, workflow_run_id=r.id,
            external_id=str(uuid.uuid4()), agent_vendor=agent.agent_vendor, agent_version="2.2.0", agent_model=agent.agent_model,
            models_used=[agent.agent_model], repo=r.repo, branch=r.branch, task_ref=r.task_ref, title=r.title,
            started_at=start, last_seen_at=r.ended_at or now - timedelta(seconds=20), ended_at=r.ended_at,
            outcome=Outcome.completed if r.status == RunStatus.succeeded else (Outcome.errored if r.status == RunStatus.failed else Outcome.unknown),
            end_reason="completed" if r.status == RunStatus.succeeded else None, turn_count=rng.randint(4, 14),
            collector_version="0.2.0", **_usage(rng, 20),
        )
        session.add(s)
        await session.flush()
        r.session_id = s.id
        files = ["src/payments/retry.py", "tests/test_retry.py"] if agent is ada else ["package.json", "package-lock.json"]
        session.add_all(_transcript(s, start, rng, r.prompt, r.result or r.error or "Working on it.", files))
        session.add_all([SessionFile(session_id=s.id, path=f, edits=rng.randint(1, 3)) for f in files])
        s.files_touched = len(files)
