"""Always-on sessions: when a machine goes away, the work does not stop.

A closed laptop does not end a Claude Code session. Claude Code is simply suspended:
no Stop hook, no SessionEnd, no result — the work freezes mid-thought, and whatever the
agent was about to do next never happens.

Flockit already knows two things that, together, mean exactly that: the session is still
open, and the machine it was running on has stopped reporting. When that happens for
someone who asked for it, their own AI developer picks the work up in the cloud, starting
from the snapshot of their working tree the agent took a minute earlier.

Deliberately conservative. A handoff needs *all* of:

- the person turned it on (``continuity = auto``); it is off until they do
- they have a personal AI developer, which only ever continues their work
- the session was alive recently, and has now been quiet for the grace period
- every machine of theirs is offline — someone thinking with their laptop open is not an
  interrupted session, and that is the most common way to be idle
- a repository, and a pushed snapshot to start from; without both there is nothing to continue
- nothing else has already continued this session
"""

from __future__ import annotations

from datetime import timedelta
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server import runs
from flockit_server.models import (
    ACTIVE_RUN_STATUSES,
    AgentSession,
    Continuity,
    Machine,
    Outcome,
    PermissionProfile,
    RunMode,
    SessionMessage,
    User,
    WorkflowRun,
)

# How long a machine must be silent before we treat the session as interrupted. The agent
# heartbeats every ~25 seconds, so this is several missed beats: a lid, not a hiccup.
MACHINE_SILENT_SECONDS = 150
# How long a session may have been quiet and still be worth continuing. Beyond this it is
# not an interrupted session, it is yesterday's.
STALE_AFTER_MINUTES = 45
# How much of the conversation to hand over.
CONTEXT_MESSAGES = 40
MAX_CONTEXT_CHARS = 24_000


async def personal_agent(db: AsyncSession, person: User) -> Optional[User]:
    return (
        await db.execute(select(User).where(User.personal_for_id == person.id, User.is_active.is_(True)))
    ).scalars().first()


async def _context(db: AsyncSession, session: AgentSession) -> str:
    """The end of the conversation, as the AI developer needs to read it."""
    rows = (
        await db.execute(
            select(SessionMessage)
            .where(SessionMessage.session_id == session.id)
            .order_by(SessionMessage.seq.desc())
            .limit(CONTEXT_MESSAGES)
        )
    ).scalars().all()
    lines: List[str] = []
    total = 0
    for m in rows:  # newest first; collected backwards, then flipped
        who = {"user": "Developer", "assistant": "Agent"}.get(m.role, m.role)
        if m.kind == "tool_use":
            text = f"[{who} ran {m.tool_name or 'a tool'}]\n{m.content}"
        elif m.kind == "tool_result":
            text = f"[result]\n{m.content}"
        else:
            text = f"{who}: {m.content}"
        total += len(text)
        if total > MAX_CONTEXT_CHARS:
            break
        lines.append(text)
    return "\n\n".join(reversed(lines))


def prompt_for(session: AgentSession, person: User, context: str) -> str:
    """What the AI developer is told. It is continuing someone's work, not starting its own."""
    return "\n".join(
        [
            f"You are continuing a coding session that {person.name} was working on when their machine went offline.",
            "",
            "This is their work, mid-flight. Pick it up where it stopped: do not start over, do not redo what is",
            "already done, and do not change direction. If the next step is ambiguous, do the smallest useful thing",
            "and say what you would ask them.",
            "",
            f"The working tree is exactly as they left it, including changes they had not committed"
            f"{f' (snapshot {session.wip_sha[:12]})' if session.wip_sha else ''}.",
            "",
            "--- the conversation so far ---",
            context or "(no transcript was captured for this session)",
            "--- end of the conversation ---",
            "",
            "Continue. When you stop, leave a short note of what you did and what is left, so they can take it back.",
        ]
    )


async def _all_machines_offline(db: AsyncSession, person: User, silent_before) -> bool:
    live = (
        await db.execute(
            select(func.count())
            .select_from(Machine)
            .where(
                Machine.user_id == person.id,
                Machine.kind == "laptop",
                Machine.revoked_at.is_(None),
                Machine.last_seen_at > silent_before,
            )
        )
    ).scalar_one()
    return live == 0


async def interrupted_sessions(db: AsyncSession) -> List[AgentSession]:
    """Live sessions whose machine has gone quiet, for people who asked us to continue them."""
    now = runs.now()
    silent_before = now - timedelta(seconds=MACHINE_SILENT_SECONDS)
    return list(
        (
            await db.execute(
                select(AgentSession)
                .join(User, User.id == AgentSession.human_owner_id)
                .where(
                    AgentSession.ended_at.is_(None),
                    AgentSession.continued_by_run_id.is_(None),
                    AgentSession.origin != "workflow",
                    AgentSession.last_seen_at < silent_before,
                    AgentSession.last_seen_at > now - timedelta(minutes=STALE_AFTER_MINUTES),
                    AgentSession.repo.is_not(None),
                    AgentSession.wip_pushed.is_(True),
                    AgentSession.wip_sha.is_not(None),
                    User.continuity == Continuity.auto,
                    User.is_active.is_(True),
                )
                .order_by(AgentSession.last_seen_at)
                .limit(20)
            )
        ).scalars().all()
    )


async def hand_over(db: AsyncSession, session: AgentSession) -> Optional[WorkflowRun]:
    """Give one interrupted session to its owner's AI developer."""
    person = await db.get(User, session.human_owner_id)
    if person is None:
        return None
    agent = await personal_agent(db, person)
    if agent is None:
        return None
    silent_before = runs.now() - timedelta(seconds=MACHINE_SILENT_SECONDS)
    if not await _all_machines_offline(db, person, silent_before):
        return None  # they are still at their desk; an idle session is not an interrupted one
    busy = (
        await db.execute(
            select(func.count())
            .select_from(WorkflowRun)
            .where(WorkflowRun.assignee_id == agent.id, WorkflowRun.status.in_(ACTIVE_RUN_STATUSES))
        )
    ).scalar_one()
    if busy:
        return None  # one at a time: their agent finishes what it has before taking more

    title = (session.title or "a session").strip()
    run = await runs.create_run(
        db,
        org_id=session.org_id,
        assignee=agent,
        title=f"Continue: {title[:180]}",
        prompt=prompt_for(session, person, await _context(db, session)),
        repo=session.repo,
        base_branch=None,
        task_ref=session.task_ref,
        mode=RunMode.auto,
        permission_profile=PermissionProfile.edit,
        trigger="continuity",
        trigger_payload={"session_id": str(session.id), "start_ref": session.wip_ref, "start_sha": session.wip_sha},
        triggered_by=person,
    )
    session.continued_by_run_id = run.id
    # The session itself is over on that machine: it was interrupted, and the work moved.
    session.ended_at = session.last_seen_at
    session.outcome = Outcome.completed
    session.end_reason = "continued"
    await runs.audit(
        db,
        session.org_id,
        person,
        "session.continued",
        "session",
        session.id,
        {"agent": agent.name, "task": str(run.id)},
    )
    return run


async def sweep(db: AsyncSession) -> int:
    """Called by the background sweeper. Returns how many sessions were handed over."""
    handed = 0
    for session in await interrupted_sessions(db):
        if await hand_over(db, session):
            handed += 1
    if handed:
        await db.commit()
    return handed


__all__ = ["sweep", "hand_over", "interrupted_sessions", "personal_agent", "prompt_for"]
