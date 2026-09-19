"""Turn collector events into session rows.

Events can arrive late, out of order, twice, or for a session that began before
the collector was installed. Every rule below exists for one of those cases:

- ``event_id`` makes retries idempotent.
- Any event type creates the session if it does not exist yet.
- ``started_at`` only ever moves earlier, ``last_seen_at`` only later.
- Non-empty values overwrite, empty values never erase.
- Activity after the sweeper marked a session abandoned reopens it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server.models import AgentSession, IngestEvent, Outcome, User
from flockit_server.schemas import IngestEventIn, IngestResult

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


async def _lock_session(db: AsyncSession, owner: User, p: _Parsed) -> AgentSession:
    s = p.event.session
    await db.execute(
        insert(AgentSession)
        .values(
            org_id=owner.org_id,
            human_owner_id=owner.id,
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
                AgentSession.org_id == owner.org_id,
                AgentSession.agent_vendor == s.agent_vendor,
                AgentSession.external_id == s.external_id,
            )
            .with_for_update(of=AgentSession)
        )
    ).scalar_one()


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


async def ingest(db: AsyncSession, owner: User, raw: List[Dict[str, Any]]) -> IngestResult:
    now = datetime.now(timezone.utc)
    parsed, rejected = _parse(raw, now)
    accepted = duplicates = 0
    for p in parsed:
        # Lock first, then check for a duplicate: a collector retry can race the
        # original request, and the row lock serialises them.
        row = await _lock_session(db, owner, p)
        seen = (await db.execute(select(IngestEvent.event_id).where(IngestEvent.event_id == p.event.event_id))).first()
        if seen is not None:
            duplicates += 1
            continue
        if row.human_owner_id != owner.id:
            # Another person's token is reporting this session id. Never reassign ownership.
            rejected += 1
            continue
        _apply(row, p)
        db.add(IngestEvent(event_id=p.event.event_id, session_id=row.id, type=p.event.type))
        await db.flush()
        accepted += 1
    await db.commit()
    return IngestResult(accepted=accepted, duplicates=duplicates, rejected=rejected)
