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
from flockit_server.models import AgentSession, Organization, Outcome, Role, Team, User
from flockit_server.security import hash_password

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
                            collector_version="0.1.0",
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
                    collector_version="0.1.0",
                )
            )

        session.add_all(rows)
        await session.commit()
    await db.dispose()
    print(f"Loaded demo organisation: {len(PEOPLE)} people, 3 teams, {len(rows)} sessions.")
    print("Sign in as maya@acme.dev (admin), daniel@acme.dev (lead) or noa@acme.dev (developer).")
    print(f"Password for every demo account: {DEMO_PASSWORD}")
    return 0
