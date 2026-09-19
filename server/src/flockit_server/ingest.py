"""Turn collector events into session rows and transcripts.

Events can arrive late, out of order, twice, or for a session that began before
the collector was installed. Every rule below exists for one of those cases:

- ``event_id`` makes retries idempotent (so token usage is never double counted).
- Any event type creates the session if it does not exist yet.
- ``started_at`` only ever moves earlier, ``last_seen_at`` only later.
- Non-empty values overwrite, empty values never erase.
- Activity after the sweeper marked a session abandoned reopens it.

Attribution: a session's ``human_owner_id`` is always a person. For a person's own
work that is them; for an AI developer's task it is the person who assigned the task
(or the AI developer's sponsor), and ``actor_id`` records the AI developer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server.models import (
    AgentSession,
    IngestEvent,
    Origin,
    Outcome,
    RunStatus,
    SessionFile,
    SessionMessage,
    User,
    UserKind,
    WorkflowRun,
)
from flockit_server.schemas import IngestEventIn, IngestResult, TranscriptIn

# Claude Code SessionEnd reasons that mean the developer ended the session on purpose.
CLEAN_END_REASONS = {"prompt_input_exit", "logout", "clear", "exit", "completed"}
ERROR_END_REASONS = {"error", "errored", "crash", "api_error"}

MAX_CLOCK_SKEW = timedelta(minutes=5)


def outcome_for(reason: str | None) -> Outcome:
    if reason in CLEAN_END_REASONS:
        return Outcome.completed
    if reason in ERROR_END_REASONS:
        return Outcome.errored
    return Outcome.unknown


@dataclass
class _Parsed:
    event: IngestEventIn
    occurred_at: datetime


@dataclass
class Attribution:
    owner: User  # always a person
    actor: User  # the person, or the AI developer doing the work
    run: Optional[WorkflowRun] = None  # the task this token was minted for, if any


def _parse(raw: List[Dict[str, Any]], now: datetime) -> tuple[list[_Parsed], int]:
    parsed, rejected = [], 0
    for item in raw:
        try:
            event = IngestEventIn.model_validate(item)
        except ValidationError:
            rejected += 1
            continue
        occurred = event.occurred_at
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        occurred = min(occurred, now + MAX_CLOCK_SKEW)  # a clock in the future cannot extend a session
        parsed.append(_Parsed(event, occurred))
    parsed.sort(key=lambda p: p.occurred_at)
    return parsed, rejected


async def attribute(db: AsyncSession, user: User, run_id: Any = None) -> Optional[Attribution]:
    """Who owns and who performed the sessions reported with this token."""
    if user.kind == UserKind.human:
        return Attribution(owner=user, actor=user)
    run = await db.get(WorkflowRun, run_id) if run_id else None
    owner = None
    if run is not None and run.triggered_by_id:
        owner = await db.get(User, run.triggered_by_id)
    if (owner is None or owner.kind != UserKind.human) and user.sponsor_id:
        owner = await db.get(User, user.sponsor_id)
    if owner is None or owner.kind != UserKind.human:
        return None  # an AI developer with no human to answer for it reports nothing
    return Attribution(owner=owner, actor=user, run=run)


async def _lock_session(db: AsyncSession, who: Attribution, p: _Parsed) -> AgentSession:
    s = p.event.session
    await db.execute(
        insert(AgentSession)
        .values(
            org_id=who.owner.org_id,
            human_owner_id=who.owner.id,
            actor_id=who.actor.id,
            origin=s.origin,
            external_id=s.external_id,
            agent_vendor=s.agent_vendor,
            started_at=p.occurred_at,
            last_seen_at=p.occurred_at,
            models_used=[],
        )
        .on_conflict_do_nothing(constraint="uq_session_external")
    )
    return (
        await db.execute(
            select(AgentSession)
            .where(
                AgentSession.org_id == who.owner.org_id,
                AgentSession.agent_vendor == s.agent_vendor,
                AgentSession.external_id == s.external_id,
            )
            .with_for_update(of=AgentSession)
        )
    ).scalar_one()


async def _link_task(db: AsyncSession, row: AgentSession, who: Attribution, p: _Parsed) -> None:
    """Connect a session to the task it was started for, and move the task along."""
    run = who.run
    task_id = p.event.session.task_id
    if run is None and task_id is not None:
        candidate = await db.get(WorkflowRun, task_id)
        if candidate is not None and candidate.assignee_id == who.actor.id:
            run = candidate
    if run is None:
        return
    row.workflow_run_id = run.id
    row.origin = Origin.workflow
    if row.task_ref is None and run.task_ref:
        row.task_ref = run.task_ref
    if run.session_id is None or run.session_id == row.id:
        run.session_id = row.id
    if run.status in (RunStatus.queued, RunStatus.starting):
        run.status = RunStatus.running
        run.started_at = run.started_at or p.occurred_at
    if p.event.type == "session.end" and run.interactive and run.status == RunStatus.running:
        # A person closed the interactive session: the task is done unless they reopen it.
        run.status = RunStatus.succeeded
        run.ended_at = p.occurred_at


def _apply(row: AgentSession, p: _Parsed) -> None:
    e, s = p.event, p.event.session
    if p.occurred_at < row.started_at:
        row.started_at = p.occurred_at
    if p.occurred_at > row.last_seen_at:
        row.last_seen_at = p.occurred_at

    for field in ("agent_version", "repo", "branch", "task_ref"):
        value = getattr(s, field)
        if value:
            setattr(row, field, value)
    if s.agent_model:
        row.agent_model = s.agent_model
        if s.agent_model not in (row.models_used or []):
            row.models_used = [*(row.models_used or []), s.agent_model]
    if e.collector_version:
        row.collector_version = e.collector_version

    if e.type == "session.activity":
        row.turn_count = (row.turn_count or 0) + 1

    if e.type == "session.end":
        row.ended_at = max(p.occurred_at, row.started_at)
        row.end_reason = s.end_reason
        row.outcome = outcome_for(s.end_reason)
    elif row.outcome == Outcome.abandoned and e.type in ("session.activity", "session.update", "session.start"):
        # The sweeper gave up on it, but the developer came back.
        row.ended_at = None
        row.outcome = Outcome.unknown


async def _apply_transcript(db: AsyncSession, row: AgentSession, t: TranscriptIn) -> None:
    if t.title and not row.title:
        row.title = t.title[:300]
    if t.messages:
        values = [
            {
                "session_id": row.id,
                "entry_id": m.id,
                "seq": m.seq,
                "role": m.role,
                "kind": m.kind,
                "tool_name": m.tool_name,
                "content": m.content,
                "occurred_at": m.at if m.at.tzinfo else m.at.replace(tzinfo=timezone.utc),
            }
            for m in t.messages
        ]
        inserted = (
            await db.execute(
                insert(SessionMessage)
                .values(values)
                .on_conflict_do_nothing(constraint="uq_session_message_entry")
                .returning(SessionMessage.kind)
            )
        ).scalars().all()
        row.message_count = (row.message_count or 0) + len(inserted)
        row.tool_calls = (row.tool_calls or 0) + sum(1 for k in inserted if k == "tool_use")
    u = t.usage
    row.tokens_input = (row.tokens_input or 0) + u.input
    row.tokens_output = (row.tokens_output or 0) + u.output
    row.tokens_cache_read = (row.tokens_cache_read or 0) + u.cache_read
    row.tokens_cache_write = (row.tokens_cache_write or 0) + u.cache_write
    if t.files:
        merged: Dict[str, int] = {}
        for f in t.files:
            merged[f.path] = merged.get(f.path, 0) + f.edits
        stmt = insert(SessionFile).values([{"session_id": row.id, "path": k, "edits": v} for k, v in merged.items()])
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["session_id", "path"], set_={"edits": SessionFile.edits + stmt.excluded.edits}
            )
        )
        row.files_touched = (
            await db.execute(select(func.count()).select_from(SessionFile).where(SessionFile.session_id == row.id))
        ).scalar_one()


async def ingest(db: AsyncSession, user: User, raw: List[Dict[str, Any]], run_id: Any = None) -> IngestResult:
    now = datetime.now(timezone.utc)
    parsed, rejected = _parse(raw, now)
    who = await attribute(db, user, run_id)
    if who is None:
        return IngestResult(accepted=0, duplicates=0, rejected=rejected + len(parsed))
    accepted = duplicates = 0
    for p in parsed:
        # Lock first, then check for a duplicate: a collector retry can race the
        # original request, and the row lock serialises them.
        row = await _lock_session(db, who, p)
        seen = (await db.execute(select(IngestEvent.event_id).where(IngestEvent.event_id == p.event.event_id))).first()
        if seen is not None:
            duplicates += 1
            continue
        if row.human_owner_id != who.owner.id or (row.actor_id and row.actor_id != who.actor.id):
            # Another person's token is reporting this session id. Never reassign ownership.
            rejected += 1
            continue
        _apply(row, p)
        await _link_task(db, row, who, p)
        if p.event.transcript is not None:
            await _apply_transcript(db, row, p.event.transcript)
        db.add(IngestEvent(event_id=p.event.event_id, session_id=row.id, type=p.event.type))
        await db.flush()
        accepted += 1
    await db.commit()
    return IngestResult(accepted=accepted, duplicates=duplicates, rejected=rejected)
