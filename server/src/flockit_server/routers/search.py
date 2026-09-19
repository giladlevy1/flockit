"""Transcripts, files touched and org-wide search over everything agents and people said and did.

Everything here goes through the same role scope as the session list: a developer
searches their own sessions, a lead their teams', an admin the organisation's.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server.db import get_db
from flockit_server.deps import current_user
from flockit_server.models import AgentSession, SessionFile, SessionMessage, User
from flockit_server.scope import visible_sessions

router = APIRouter(tags=["search"])


async def _visible(db: AsyncSession, user: User, session_id: uuid.UUID) -> AgentSession:
    row = (
        await db.execute(select(AgentSession).where(AgentSession.id == session_id, visible_sessions(user)))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Session not found")
    return row


@router.get("/api/sessions/{session_id}/transcript")
async def transcript(
    session_id: uuid.UUID,
    after: int = Query(default=-1, ge=-1),
    limit: int = Query(default=500, ge=1, le=2000),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _visible(db, user, session_id)
    rows = (
        await db.execute(
            select(SessionMessage)
            .where(SessionMessage.session_id == session_id, SessionMessage.seq > after)
            .order_by(SessionMessage.seq, SessionMessage.id)
            .limit(limit)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "seq": m.seq,
                "role": m.role,
                "kind": m.kind,
                "tool_name": m.tool_name,
                "content": m.content,
                "at": m.occurred_at,
            }
            for m in rows
        ],
        "has_more": len(rows) == limit,
    }


@router.get("/api/sessions/{session_id}/files")
async def files(session_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> list:
    await _visible(db, user, session_id)
    rows = (
        await db.execute(
            select(SessionFile).where(SessionFile.session_id == session_id).order_by(SessionFile.edits.desc(), SessionFile.path)
        )
    ).scalars().all()
    return [{"path": f.path, "edits": f.edits} for f in rows]


@router.get("/api/search")
async def search(
    q: str = Query(min_length=2, max_length=200),
    kind: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Full-text search across every visible transcript: prompts, replies, commands, tool output."""
    query = func.websearch_to_tsquery("simple", q)
    conds = [SessionMessage.search.op("@@")(query), visible_sessions(user)]
    if kind:
        conds.append(SessionMessage.kind.in_([k for k in kind if k in ("text", "tool_use", "tool_result")]))
    base = select(SessionMessage.id).join(AgentSession, AgentSession.id == SessionMessage.session_id).where(*conds)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    headline = func.ts_headline(
        "simple",
        SessionMessage.content,
        query,
        literal_column("'StartSel=<<, StopSel=>>, MaxWords=40, MinWords=12, MaxFragments=2, FragmentDelimiter= … '"),
    )
    rows = (
        await db.execute(
            select(SessionMessage, AgentSession, headline.label("snippet"), func.ts_rank(SessionMessage.search, query).label("rank"))
            .join(AgentSession, AgentSession.id == SessionMessage.session_id)
            .where(*conds)
            .order_by(literal_column("rank").desc(), SessionMessage.occurred_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = []
    for m, sess, snippet, _rank in rows:
        actor = sess.actor if sess.actor is not None and sess.actor_id != sess.human_owner_id else None
        items.append(
            {
                "session_id": sess.id,
                "seq": m.seq,
                "role": m.role,
                "kind": m.kind,
                "tool_name": m.tool_name,
                "snippet": snippet,
                "at": m.occurred_at,
                "session": {
                    "title": sess.title,
                    "repo": sess.repo,
                    "branch": sess.branch,
                    "owner": sess.owner.name,
                    "actor": actor.name if actor else None,
                    "agent_model": sess.agent_model,
                },
            }
        )
    return {"items": items, "total": total}
