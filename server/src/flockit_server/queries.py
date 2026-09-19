"""Read side of the R&D view. Every function takes the viewer and applies role scope."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Select, and_, case, distinct, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server.models import AgentSession, Origin, Outcome, Role, Team, TeamMember, User, UserKind, WorkflowRun
from flockit_server.schemas import ActorOut, OwnerOut, SessionOut
from flockit_server.scope import visible_sessions, visible_users
from flockit_server.settings import get_settings


@dataclass
class Filters:
    owner: List[uuid.UUID] = field(default_factory=list)
    team: List[uuid.UUID] = field(default_factory=list)
    repo: List[str] = field(default_factory=list)
    vendor: List[str] = field(default_factory=list)
    model: List[str] = field(default_factory=list)
    outcome: List[Outcome] = field(default_factory=list)
    status: List[str] = field(default_factory=list)
    origin: List[Origin] = field(default_factory=list)
    task_ref: Optional[str] = None
    actor_kind: Optional[str] = None  # human | ai
    task: Optional[uuid.UUID] = None
    q: Optional[str] = None
    since: Optional[datetime] = None
    until: Optional[datetime] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _live_cutoff() -> datetime:
    return _now() - timedelta(minutes=get_settings().live_window_minutes)


_END = func.coalesce(AgentSession.ended_at, AgentSession.last_seen_at)
# "claude-haiku-4-5-20251001" and "claude-haiku-4-5" are the same model for reporting.
MODEL = func.regexp_replace(AgentSession.agent_model, "-[0-9]{8}$", "")
_SECONDS = func.extract("epoch", _END - AgentSession.started_at)


def _conditions(viewer: User, f: Filters) -> list:
    conds: list = [visible_sessions(viewer)]
    if f.owner:
        conds.append(or_(AgentSession.human_owner_id.in_(f.owner), AgentSession.actor_id.in_(f.owner)))
    if f.team:
        conds.append(AgentSession.human_owner_id.in_(select(TeamMember.user_id).where(TeamMember.team_id.in_(f.team))))
    if f.repo:
        conds.append(AgentSession.repo.in_(f.repo))
    if f.vendor:
        conds.append(AgentSession.agent_vendor.in_(f.vendor))
    if f.model:
        conds.append(MODEL.in_(f.model))
    if f.outcome:
        conds.append(AgentSession.outcome.in_(f.outcome))
    if f.origin:
        conds.append(AgentSession.origin.in_(f.origin))
    if f.status:
        cutoff = _live_cutoff()
        parts = []
        if "live" in f.status:
            parts.append(and_(AgentSession.ended_at.is_(None), AgentSession.last_seen_at >= cutoff))
        if "idle" in f.status:
            parts.append(and_(AgentSession.ended_at.is_(None), AgentSession.last_seen_at < cutoff))
        if "ended" in f.status:
            parts.append(AgentSession.ended_at.is_not(None))
        if parts:
            conds.append(or_(*parts))
    if f.task_ref:
        conds.append(AgentSession.task_ref == f.task_ref)
    if f.task:
        conds.append(AgentSession.workflow_run_id == f.task)
    if f.actor_kind in ("human", "ai"):
        kind_ids = select(User.id).where(User.kind == UserKind(f.actor_kind))
        if f.actor_kind == "human":
            conds.append(or_(AgentSession.actor_id.is_(None), AgentSession.actor_id.in_(kind_ids)))
        else:
            conds.append(AgentSession.actor_id.in_(kind_ids))
    if f.since:
        conds.append(_END >= f.since)  # overlaps the window, not just started in it
    if f.until:
        conds.append(AgentSession.started_at < f.until)
    if f.q:
        like = "%" + f.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        owner_match = select(User.id).where(or_(User.name.ilike(like), User.email.ilike(like)))
        conds.append(
            or_(
                AgentSession.repo.ilike(like),
                AgentSession.branch.ilike(like),
                AgentSession.task_ref.ilike(like),
                AgentSession.agent_model.ilike(like),
                AgentSession.title.ilike(like),
                AgentSession.human_owner_id.in_(owner_match),
                AgentSession.actor_id.in_(owner_match),
            )
        )
    return conds


def _status(row: AgentSession, cutoff: datetime) -> str:
    if row.ended_at is not None:
        return "ended"
    return "live" if row.last_seen_at >= cutoff else "idle"


async def _team_names(db: AsyncSession, viewer: User, user_ids: set[uuid.UUID]) -> Dict[uuid.UUID, List[str]]:
    """Team names per owner, limited to teams the viewer may see (all for admins, their own otherwise)."""
    if not user_ids:
        return {}
    q = (
        select(TeamMember.user_id, Team.name)
        .join(Team, Team.id == TeamMember.team_id)
        .where(TeamMember.user_id.in_(user_ids), Team.org_id == viewer.org_id)
        .order_by(Team.name)
    )
    if viewer.role != Role.admin:
        q = q.where(Team.id.in_(select(TeamMember.team_id).where(TeamMember.user_id == viewer.id)))
    rows = await db.execute(q)
    out: Dict[uuid.UUID, List[str]] = {}
    for uid, name in rows:
        out.setdefault(uid, []).append(name)
    return out


async def _tasks(db: AsyncSession, rows) -> Dict[uuid.UUID, dict]:
    ids = {r.workflow_run_id for r in rows if r.workflow_run_id}
    if not ids:
        return {}
    found = await db.execute(select(WorkflowRun.id, WorkflowRun.title, WorkflowRun.status).where(WorkflowRun.id.in_(ids)))
    return {i: {"id": i, "title": t, "status": st.value} for i, t, st in found}


def to_out(
    row: AgentSession, teams: Dict[uuid.UUID, List[str]], cutoff: datetime, tasks: Optional[Dict[uuid.UUID, dict]] = None
) -> SessionOut:
    end = row.ended_at or row.last_seen_at
    actor = row.actor if row.actor is not None and row.actor_id != row.human_owner_id else None
    return SessionOut(
        id=row.id,
        owner=OwnerOut(id=row.owner.id, name=row.owner.name, email=row.owner.email, teams=teams.get(row.owner.id, [])),
        actor=ActorOut(id=actor.id, name=actor.name, kind=actor.kind.value) if actor else None,
        title=row.title,
        task=(tasks or {}).get(row.workflow_run_id) if row.workflow_run_id else None,
        tokens_input=row.tokens_input or 0,
        tokens_output=row.tokens_output or 0,
        tokens_cache_read=row.tokens_cache_read or 0,
        tokens_cache_write=row.tokens_cache_write or 0,
        tool_calls=row.tool_calls or 0,
        message_count=row.message_count or 0,
        files_touched=row.files_touched or 0,
        origin=row.origin,
        agent_vendor=row.agent_vendor,
        agent_version=row.agent_version,
        agent_model=row.agent_model,
        models_used=list(row.models_used or []),
        repo=row.repo,
        branch=row.branch,
        task_ref=row.task_ref,
        started_at=row.started_at,
        last_seen_at=row.last_seen_at,
        ended_at=row.ended_at,
        duration_seconds=max(0, int((end - row.started_at).total_seconds())),
        status=_status(row, cutoff),  # type: ignore[arg-type]
        outcome=row.outcome,
        end_reason=row.end_reason,
        turn_count=row.turn_count,
    )


SORTS = {
    "started_at": AgentSession.started_at,
    "last_seen_at": AgentSession.last_seen_at,
    "duration": _SECONDS,
    "turns": AgentSession.turn_count,
    "repo": AgentSession.repo,
}


async def list_sessions(
    db: AsyncSession, viewer: User, f: Filters, limit: int, offset: int, sort: str = "-started_at"
) -> tuple[list[SessionOut], int]:
    conds = _conditions(viewer, f)
    total = (await db.execute(select(func.count()).select_from(AgentSession).where(*conds))).scalar_one()
    desc = sort.startswith("-")
    column = SORTS.get(sort.lstrip("-"), AgentSession.started_at)
    order = column.desc().nulls_last() if desc else column.asc().nulls_last()
    # Live sessions first: that is what a leader opens the page to see.
    live_first = case((and_(AgentSession.ended_at.is_(None), AgentSession.last_seen_at >= _live_cutoff()), 0), else_=1)
    stmt: Select = (
        select(AgentSession).where(*conds).order_by(live_first, order, AgentSession.id).limit(limit).offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().unique().all()
    teams = await _team_names(db, viewer, {r.human_owner_id for r in rows})
    tasks = await _tasks(db, rows)
    cutoff = _live_cutoff()
    return [to_out(r, teams, cutoff, tasks) for r in rows], total


async def get_session(db: AsyncSession, viewer: User, session_id: uuid.UUID) -> Optional[SessionOut]:
    row = (
        await db.execute(select(AgentSession).where(AgentSession.id == session_id, visible_sessions(viewer)))
    ).scalar_one_or_none()
    if row is None:
        return None
    teams = await _team_names(db, viewer, {row.human_owner_id})
    return to_out(row, teams, _live_cutoff(), await _tasks(db, [row]))


async def summary(db: AsyncSession, viewer: User, f: Filters) -> Dict[str, Any]:
    conds = _conditions(viewer, f)
    cutoff = _live_cutoff()
    live = and_(AgentSession.ended_at.is_(None), AgentSession.last_seen_at >= cutoff)

    totals = (
        await db.execute(
            select(
                func.count(),
                func.count(distinct(AgentSession.human_owner_id)),
                func.count(distinct(AgentSession.repo)),
                func.coalesce(func.sum(_SECONDS), 0),
                func.count().filter(live),
                func.count(distinct(AgentSession.human_owner_id)).filter(live),
                func.coalesce(func.sum(AgentSession.turn_count), 0),
                func.coalesce(func.sum(AgentSession.tokens_input + AgentSession.tokens_cache_read + AgentSession.tokens_cache_write), 0),
                func.coalesce(func.sum(AgentSession.tokens_output), 0),
                func.coalesce(func.sum(AgentSession.tool_calls), 0),
                func.count().filter(AgentSession.actor_id.in_(select(User.id).where(User.kind == UserKind.ai))),
                func.count().filter(AgentSession.workflow_run_id.is_not(None)),
            ).where(*conds)
        )
    ).one()

    outcomes = {
        o.value: n
        for o, n in (
            await db.execute(select(AgentSession.outcome, func.count()).where(*conds).group_by(AgentSession.outcome))
        ).all()
    }

    by_agent = [
        {"vendor": v, "model": m, "sessions": n, "hours": round(float(s or 0) / 3600, 2), "people": p}
        for v, m, n, s, p in (
            await db.execute(
                select(
                    AgentSession.agent_vendor,
                    MODEL,
                    func.count(),
                    func.sum(_SECONDS),
                    func.count(distinct(AgentSession.human_owner_id)),
                )
                .where(*conds)
                .group_by(AgentSession.agent_vendor, MODEL)
                .order_by(func.sum(_SECONDS).desc().nulls_last())
            )
        ).all()
    ]

    top_repos = [
        {
            "repo": r,
            "sessions": n,
            "hours": round(float(s or 0) / 3600, 2),
            "people": p,
            "abandoned": a,
        }
        for r, n, s, p, a in (
            await db.execute(
                select(
                    AgentSession.repo,
                    func.count(),
                    func.sum(_SECONDS),
                    func.count(distinct(AgentSession.human_owner_id)),
                    func.count().filter(AgentSession.outcome == Outcome.abandoned),
                )
                .where(*conds, AgentSession.repo.is_not(None))
                .group_by(AgentSession.repo)
                .order_by(func.sum(_SECONDS).desc().nulls_last())
                .limit(8)
            )
        ).all()
    ]

    # The same ticket worked by more than one person: the duplicated effort a leader cannot see today.
    overlap_rows = (
        await db.execute(
            select(
                AgentSession.task_ref,
                func.count(),
                func.sum(_SECONDS),
                func.array_agg(distinct(User.name)),
                func.max(AgentSession.last_seen_at),
            )
            .join(User, User.id == AgentSession.human_owner_id)
            .where(*conds, AgentSession.task_ref.is_not(None))
            .group_by(AgentSession.task_ref)
            .having(func.count(distinct(AgentSession.human_owner_id)) > 1)
            .order_by(func.sum(_SECONDS).desc())
            .limit(6)
        )
    ).all()
    overlaps = [
        {"task_ref": t, "sessions": n, "hours": round(float(s or 0) / 3600, 2), "people": sorted(names), "last_seen_at": last}
        for t, n, s, names, last in overlap_rows
    ]

    day = func.date_trunc("day", AgentSession.started_at).label("day")
    daily = [
        {"day": d.date().isoformat(), "sessions": n, "hours": round(float(s or 0) / 3600, 2)}
        for d, n, s in (
            await db.execute(select(day, func.count(), func.sum(_SECONDS)).where(*conds).group_by(day).order_by(day))
        ).all()
    ]

    return {
        "sessions": totals[0],
        "people": totals[1],
        "repos": totals[2],
        "agent_hours": round(float(totals[3]) / 3600, 2),
        "live_sessions": totals[4],
        "live_people": totals[5],
        "turns": int(totals[6]),
        "tokens_input": int(totals[7]),
        "tokens_output": int(totals[8]),
        "tool_calls": int(totals[9]),
        "ai_sessions": int(totals[10]),
        "task_sessions": int(totals[11]),
        "outcomes": {o.value: outcomes.get(o.value, 0) for o in Outcome},
        "by_agent": by_agent,
        "top_repos": top_repos,
        "overlaps": overlaps,
        "daily": daily,
    }


async def facets(db: AsyncSession, viewer: User) -> Dict[str, Any]:
    scope = visible_sessions(viewer)
    people = (
        await db.execute(select(User.id, User.name, User.email).where(visible_users(viewer)).order_by(User.name))
    ).all()
    team_q = select(Team.id, Team.name).where(Team.org_id == viewer.org_id).order_by(Team.name)
    if viewer.role != Role.admin:
        team_q = team_q.where(Team.id.in_(select(TeamMember.team_id).where(TeamMember.user_id == viewer.id)))
    teams = (await db.execute(team_q)).all()

    async def distinct_values(column) -> list[str]:
        rows = await db.execute(select(column).where(scope, column.is_not(None)).distinct().order_by(column))
        return [r[0] for r in rows]

    return {
        "people": [{"id": i, "name": n, "email": e} for i, n, e in people],
        "teams": [{"id": i, "name": n} for i, n in teams],
        "repos": await distinct_values(AgentSession.repo),
        "vendors": await distinct_values(AgentSession.agent_vendor),
        "models": [
            r[0]
            for r in await db.execute(select(MODEL).where(scope, AgentSession.agent_model.is_not(None)).distinct().order_by(MODEL))
        ],
    }


async def sweep_abandoned(db: AsyncSession) -> int:
    """Mark sessions with no activity for the abandonment window as abandoned."""
    from sqlalchemy import update

    cutoff = _now() - timedelta(hours=get_settings().abandon_after_hours)
    result = await db.execute(
        update(AgentSession)
        .where(AgentSession.ended_at.is_(None), AgentSession.last_seen_at < cutoff)
        .values(ended_at=AgentSession.last_seen_at, outcome=Outcome.abandoned, end_reason=literal("inactive"))
    )
    await db.commit()
    return result.rowcount or 0
