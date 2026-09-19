from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server import runs, scope
from flockit_server.db import get_db
from flockit_server.deps import current_user
from flockit_server.models import AgentSession, Machine, Origin, Outcome, RunMode, User
from flockit_server.queries import Filters, facets, get_session, list_sessions, summary
from flockit_server.schemas import SessionOut, SessionPage

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def filters(
    owner: List[uuid.UUID] = Query(default=[]),
    team: List[uuid.UUID] = Query(default=[]),
    repo: List[str] = Query(default=[]),
    vendor: List[str] = Query(default=[]),
    model: List[str] = Query(default=[]),
    outcome: List[Outcome] = Query(default=[]),
    status: List[str] = Query(default=[]),
    origin: List[Origin] = Query(default=[]),
    task_ref: Optional[str] = Query(default=None, max_length=300),
    actor_kind: Optional[str] = Query(default=None, pattern="^(human|ai)$"),
    task: Optional[uuid.UUID] = None,
    q: Optional[str] = Query(default=None, max_length=200),
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> Filters:
    return Filters(
        owner=owner,
        team=team,
        repo=repo,
        vendor=vendor,
        model=model,
        outcome=outcome,
        status=[s for s in status if s in ("live", "idle", "ended")],
        origin=origin,
        task_ref=task_ref or None,
        actor_kind=actor_kind,
        task=task,
        q=(q or "").strip() or None,
        since=since,
        until=until,
    )


@router.get("", response_model=SessionPage)
async def get_sessions(
    f: Filters = Depends(filters),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="-started_at", pattern=r"^-?(started_at|last_seen_at|duration|turns|repo)$"),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionPage:
    items, total = await list_sessions(db, user, f, limit, offset, sort)
    return SessionPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/summary")
async def get_summary(
    f: Filters = Depends(filters), user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    return await summary(db, user, f)


@router.get("/facets")
async def get_facets(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return await facets(db, user)


@router.get("/{session_id}", response_model=SessionOut)
async def get_one(session_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    found = await get_session(db, user, session_id)
    if found is None:
        raise HTTPException(404, "Session not found")
    return found


class ContinueOut(BaseModel):
    task_id: uuid.UUID
    status: str
    machine: Optional[str] = None


@router.post("/{session_id}/continue", response_model=ContinueOut, status_code=201)
async def continue_session(
    session_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> ContinueOut:
    """Pick a session back up on this person's own machine.

    The agent reopens the original Claude Code session with ``--resume`` in the same
    repository, so the context is the one that was there when it stopped — the point of
    keeping the transcript in the first place. Only your own sessions, and only Claude
    Code: there is nothing to resume for a runner sandbox that no longer exists.
    """
    s = (
        await db.execute(select(AgentSession).where(AgentSession.id == session_id, scope.visible_sessions(user)))
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(404, "Session not found")
    if s.human_owner_id != user.id:
        raise HTTPException(403, "You can only continue your own sessions")
    if s.agent_vendor != "claude-code" or not s.external_id:
        raise HTTPException(409, "Only Claude Code sessions can be continued")
    if s.origin == Origin.workflow:
        raise HTTPException(409, "This was an AI developer's sandbox session; it no longer exists to resume")
    run = await runs.create_run(
        db,
        org_id=user.org_id,
        assignee=user,
        title=f"Continue: {(s.title or 'session')[:200]}",
        prompt="Continue where we left off. Say what you were doing and what is left before you change anything.",
        repo=s.repo,
        base_branch=None,
        task_ref=s.task_ref,
        mode=RunMode.ask,
        trigger="continue",
        trigger_payload={"resume": s.external_id, "session_id": str(s.id)},
        triggered_by=user,
    )
    await db.commit()
    machine = (
        await db.execute(
            select(Machine.name).where(Machine.user_id == user.id, Machine.kind == "laptop", Machine.revoked_at.is_(None))
        )
    ).scalars().first()
    return ContinueOut(task_id=run.id, status=run.status.value, machine=machine)
