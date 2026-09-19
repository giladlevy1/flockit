from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server.db import get_db
from flockit_server.deps import current_user
from flockit_server.models import Origin, Outcome, User
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
