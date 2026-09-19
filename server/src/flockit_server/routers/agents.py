"""AI developers, runners and the audit log."""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server import runs
from flockit_server.db import get_db
from flockit_server.deps import current_user, require_admin
from flockit_server.models import (
    AgentSession,
    AuditEvent,
    DispatchMode,
    Machine,
    Role,
    RunStatus,
    Team,
    User,
    UserKind,
    WorkflowRun,
)
from flockit_server.security import hash_token

router = APIRouter(tags=["agents"])

ONLINE_SECONDS = 90
VENDORS = ("claude-code", "codex")


def online(m: Machine) -> bool:
    return bool(m.last_seen_at and (runs.now() - m.last_seen_at).total_seconds() < ONLINE_SECONDS)


# --- AI developers ---------------------------------------------------------------


class AiDevIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    agent_vendor: str = Field(default="claude-code")
    agent_model: Optional[str] = Field(default=None, max_length=120)
    runner_pool: Optional[str] = Field(default=None, max_length=64, pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    sponsor_id: Optional[uuid.UUID] = None
    instructions: Optional[str] = Field(default=None, max_length=20_000)
    team_ids: List[uuid.UUID] = []
    is_active: bool = True


class AiDevOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    agent_vendor: str
    agent_model: Optional[str]
    runner_pool: Optional[str]
    sponsor: Optional[dict]
    instructions: Optional[str]
    teams: List[dict]
    is_active: bool
    created_at: datetime
    stats: dict
    current_task: Optional[dict]


async def _ai_out(db: AsyncSession, u: User) -> AiDevOut:
    counts = {
        s.value: n
        for s, n in (
            await db.execute(
                select(WorkflowRun.status, func.count()).where(WorkflowRun.assignee_id == u.id).group_by(WorkflowRun.status)
            )
        ).all()
    }
    tokens, cost = (
        await db.execute(
            select(
                func.coalesce(func.sum(AgentSession.tokens_input + AgentSession.tokens_output), 0),
                func.coalesce(func.sum(WorkflowRun.cost_usd), 0.0),
            )
            .select_from(WorkflowRun)
            .outerjoin(AgentSession, AgentSession.id == WorkflowRun.session_id)
            .where(WorkflowRun.assignee_id == u.id)
        )
    ).one()
    current = (
        await db.execute(
            select(WorkflowRun)
            .where(WorkflowRun.assignee_id == u.id, WorkflowRun.status.in_([RunStatus.starting, RunStatus.running]))
            .order_by(WorkflowRun.started_at.desc().nulls_last())
            .limit(1)
        )
    ).scalar_one_or_none()
    sponsor = await db.get(User, u.sponsor_id) if u.sponsor_id else None
    return AiDevOut(
        id=u.id,
        name=u.name,
        email=u.email,
        agent_vendor=u.agent_vendor or "claude-code",
        agent_model=u.agent_model,
        runner_pool=u.runner_pool,
        sponsor={"id": sponsor.id, "name": sponsor.name} if sponsor else None,
        instructions=u.instructions,
        teams=[{"id": t.id, "name": t.name} for t in sorted(u.teams, key=lambda t: t.name)],
        is_active=u.is_active,
        created_at=u.created_at,
        stats={"tasks": counts, "tokens": int(tokens), "cost_usd": round(float(cost), 2)},
        current_task={"id": current.id, "title": current.title, "status": current.status.value} if current else None,
    )


async def _teams(db: AsyncSession, org_id: uuid.UUID, ids: List[uuid.UUID]) -> List[Team]:
    if not ids:
        return []
    found = (await db.execute(select(Team).where(Team.org_id == org_id, Team.id.in_(ids)))).scalars().all()
    if len(found) != len(set(ids)):
        raise HTTPException(400, "Unknown team")
    return list(found)


def _apply(u: User, body: AiDevIn) -> None:
    if body.agent_vendor not in VENDORS:
        raise HTTPException(422, "agent_vendor must be claude-code or codex")
    u.name = body.name.strip()
    u.agent_vendor = body.agent_vendor
    u.agent_model = (body.agent_model or "").strip() or None
    u.runner_pool = body.runner_pool or None
    u.instructions = (body.instructions or "").strip() or None
    u.is_active = body.is_active


@router.get("/api/ai-developers", response_model=List[AiDevOut])
async def list_ai_devs(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(User).where(User.org_id == user.org_id, User.kind == UserKind.ai).order_by(User.is_active.desc(), User.name)
        )
    ).scalars().all()
    return [await _ai_out(db, u) for u in rows]


@router.post("/api/ai-developers", response_model=AiDevOut, status_code=201)
async def create_ai_dev(body: AiDevIn, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    slug = re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-")[:40] or "agent"
    u = User(
        org_id=admin.org_id,
        email=f"{slug}-{secrets.token_hex(3)}@agents.flockit.local",
        name=body.name,
        role=Role.developer,
        kind=UserKind.ai,
        dispatch_mode=DispatchMode.auto,
        password_hash=None,
    )
    _apply(u, body)
    sponsor = await db.get(User, body.sponsor_id or admin.id)
    if sponsor is None or sponsor.org_id != admin.org_id or sponsor.kind != UserKind.human:
        raise HTTPException(400, "The sponsor must be a person in this organisation")
    u.sponsor_id = sponsor.id
    u.teams = await _teams(db, admin.org_id, body.team_ids)
    db.add(u)
    await db.flush()
    await runs.audit(db, admin.org_id, admin, "ai_developer.created", "user", u.id, {"name": u.name, "vendor": u.agent_vendor})
    await db.commit()
    await db.refresh(u)
    return await _ai_out(db, u)


@router.put("/api/ai-developers/{user_id}", response_model=AiDevOut)
async def update_ai_dev(
    user_id: uuid.UUID, body: AiDevIn, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    u = (
        await db.execute(select(User).where(User.id == user_id, User.org_id == admin.org_id, User.kind == UserKind.ai))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(404, "AI developer not found")
    _apply(u, body)
    if body.sponsor_id:
        sponsor = await db.get(User, body.sponsor_id)
        if sponsor is None or sponsor.org_id != admin.org_id or sponsor.kind != UserKind.human:
            raise HTTPException(400, "The sponsor must be a person in this organisation")
        u.sponsor_id = sponsor.id
    u.teams = await _teams(db, admin.org_id, body.team_ids)
    await runs.audit(db, admin.org_id, admin, "ai_developer.updated", "user", u.id, {"name": u.name})
    await db.commit()
    await db.refresh(u)
    return await _ai_out(db, u)


# --- Runners -------------------------------------------------------------------


class RunnerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    pool: Optional[str] = Field(default=None, max_length=64, pattern=r"^[a-z0-9][a-z0-9_\-]*$")


class RunnerOut(BaseModel):
    id: uuid.UUID
    name: str
    pool: Optional[str]
    token_prefix: Optional[str]
    platform: Optional[str]
    version: Optional[str]
    capabilities: Optional[dict]
    capacity: int
    online: bool
    last_seen_at: Optional[datetime]
    created_at: datetime
    running: int
    token: Optional[str] = None


async def _runner_out(db: AsyncSession, m: Machine, token: Optional[str] = None) -> RunnerOut:
    running = (
        await db.execute(
            select(func.count()).select_from(WorkflowRun).where(
                WorkflowRun.machine_id == m.id, WorkflowRun.status.in_([RunStatus.starting, RunStatus.running])
            )
        )
    ).scalar_one()
    return RunnerOut(
        id=m.id,
        name=m.name,
        pool=m.pool,
        token_prefix=m.token_prefix,
        platform=m.platform,
        version=m.version,
        capabilities=m.capabilities,
        capacity=m.capacity,
        online=online(m),
        last_seen_at=m.last_seen_at,
        created_at=m.created_at,
        running=running,
        token=token,
    )


@router.get("/api/runners", response_model=List[RunnerOut])
async def list_runners(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Machine)
            .where(Machine.org_id == user.org_id, Machine.kind == "runner", Machine.revoked_at.is_(None))
            .order_by(Machine.created_at)
        )
    ).scalars().all()
    return [await _runner_out(db, m) for m in rows]


@router.post("/api/runners", response_model=RunnerOut, status_code=201)
async def create_runner(body: RunnerIn, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    token = "frn_" + secrets.token_urlsafe(32)
    m = Machine(
        org_id=admin.org_id,
        kind="runner",
        name=body.name.strip(),
        pool=body.pool,
        token_hash=hash_token(token),
        token_prefix=token[:10],
    )
    db.add(m)
    await db.flush()
    await runs.audit(db, admin.org_id, admin, "runner.created", "machine", m.id, {"name": m.name, "pool": m.pool})
    await db.commit()
    return await _runner_out(db, m, token)


@router.delete("/api/runners/{machine_id}", status_code=204)
async def revoke_runner(machine_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    m = (
        await db.execute(select(Machine).where(Machine.id == machine_id, Machine.org_id == admin.org_id, Machine.kind == "runner"))
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Runner not found")
    m.revoked_at = runs.now()
    await runs.audit(db, admin.org_id, admin, "runner.revoked", "machine", m.id, {"name": m.name})
    await db.commit()


@router.get("/api/machines/me")
async def my_machines(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> list:
    rows = (
        await db.execute(
            select(Machine).where(Machine.user_id == user.id, Machine.kind == "laptop", Machine.revoked_at.is_(None))
        )
    ).scalars().all()
    return [
        {"id": m.id, "name": m.name, "platform": m.platform, "version": m.version, "online": online(m), "last_seen_at": m.last_seen_at}
        for m in rows
    ]


@router.delete("/api/machines/{machine_id}", status_code=204)
async def remove_my_machine(machine_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    m = (
        await db.execute(select(Machine).where(Machine.id == machine_id, Machine.user_id == user.id))
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Machine not found")
    m.revoked_at = runs.now()
    await db.commit()


# --- Audit -----------------------------------------------------------------------


@router.get("/api/audit")
async def audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    before: Optional[int] = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    q = select(AuditEvent, User.name).outerjoin(User, User.id == AuditEvent.actor_id).where(AuditEvent.org_id == admin.org_id)
    if before:
        q = q.where(AuditEvent.id < before)
    rows = (await db.execute(q.order_by(AuditEvent.id.desc()).limit(limit))).all()
    return {
        "items": [
            {
                "id": e.id,
                "actor": name or "Flockit",
                "action": e.action,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "detail": e.detail,
                "created_at": e.created_at,
            }
            for e, name in rows
        ]
    }
