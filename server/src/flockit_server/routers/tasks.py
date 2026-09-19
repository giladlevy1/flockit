"""Tasks: work assigned to a person or an AI developer, from a workflow or directly."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server import runs
from flockit_server.db import get_db
from flockit_server.deps import current_user
from flockit_server.models import (
    ACTIVE_RUN_STATUSES,
    Machine,
    PermissionProfile,
    RunMode,
    RunStatus,
    User,
    UserKind,
    WorkflowRun,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class PersonRef(BaseModel):
    id: uuid.UUID
    name: str
    kind: str


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    prompt: str
    repo: Optional[str]
    base_branch: Optional[str]
    branch: Optional[str]
    task_ref: Optional[str]
    status: RunStatus
    mode: RunMode
    permission_profile: PermissionProfile
    interactive: bool
    trigger: str
    assignee: Optional[PersonRef]
    triggered_by: Optional[PersonRef]
    workflow: Optional[dict]
    machine: Optional[dict]
    session_id: Optional[uuid.UUID]
    result: Optional[str]
    error: Optional[str]
    pr_url: Optional[str]
    cost_usd: Optional[float]
    created_at: datetime
    updated_at: datetime
    accepted_at: Optional[datetime]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]


def _person(u: Optional[User]) -> Optional[PersonRef]:
    return PersonRef(id=u.id, name=u.name, kind=u.kind.value) if u else None


def task_out(r: WorkflowRun) -> TaskOut:
    return TaskOut(
        id=r.id,
        title=r.title,
        prompt=r.prompt,
        repo=r.repo,
        base_branch=r.base_branch,
        branch=r.branch,
        task_ref=r.task_ref,
        status=r.status,
        mode=r.mode,
        permission_profile=r.permission_profile,
        interactive=r.interactive,
        trigger=r.trigger,
        assignee=_person(r.assignee),
        triggered_by=_person(r.triggered_by),
        workflow={"id": r.workflow.id, "name": r.workflow.name} if r.workflow else None,
        machine={"id": r.machine.id, "name": r.machine.name, "kind": r.machine.kind} if r.machine else None,
        session_id=r.session_id,
        result=r.result,
        error=r.error,
        pr_url=r.pr_url,
        cost_usd=r.cost_usd,
        created_at=r.created_at,
        updated_at=r.updated_at,
        accepted_at=r.accepted_at,
        started_at=r.started_at,
        ended_at=r.ended_at,
    )


class TaskPage(BaseModel):
    items: List[TaskOut]
    total: int
    counts: dict


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    prompt: str = Field(min_length=1, max_length=50_000)
    repo: Optional[str] = Field(default=None, max_length=300)
    base_branch: Optional[str] = Field(default=None, max_length=200)
    task_ref: Optional[str] = Field(default=None, max_length=300)
    assignee_id: uuid.UUID
    mode: RunMode = RunMode.ask
    permission_profile: PermissionProfile = PermissionProfile.edit


class AcceptIn(BaseModel):
    interactive: bool = True


class DeclineIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=2000)


async def load_run(db: AsyncSession, viewer: User, run_id: uuid.UUID) -> WorkflowRun:
    run = (
        await db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id, runs.visible_runs(viewer)))
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "Task not found")
    return run


@router.get("", response_model=TaskPage)
async def list_tasks(
    view: Literal["mine", "all"] = "all",
    status: List[RunStatus] = Query(default=[]),
    assignee: List[uuid.UUID] = Query(default=[]),
    workflow: Optional[uuid.UUID] = None,
    q: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskPage:
    conds = [runs.visible_runs(user)]
    if view == "mine":
        conds = [WorkflowRun.assignee_id == user.id]
    if assignee:
        conds.append(WorkflowRun.assignee_id.in_(assignee))
    if workflow:
        conds.append(WorkflowRun.workflow_id == workflow)
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conds.append(or_(WorkflowRun.title.ilike(like), WorkflowRun.repo.ilike(like), WorkflowRun.task_ref.ilike(like)))
    counts = {
        s.value: n
        for s, n in (
            await db.execute(select(WorkflowRun.status, func.count()).where(*conds).group_by(WorkflowRun.status))
        ).all()
    }
    if status:
        conds.append(WorkflowRun.status.in_(status))
    total = (await db.execute(select(func.count()).select_from(WorkflowRun).where(*conds))).scalar_one()
    rows = (
        await db.execute(
            select(WorkflowRun).where(*conds).order_by(WorkflowRun.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().unique().all()
    return TaskPage(items=[task_out(r) for r in rows], total=total, counts=counts)


@router.get("/inbox")
async def inbox(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """What needs this person's attention, and whether one of their machines can run it."""
    offered = (
        await db.execute(
            select(func.count()).select_from(WorkflowRun).where(
                WorkflowRun.assignee_id == user.id, WorkflowRun.status == RunStatus.offered
            )
        )
    ).scalar_one()
    active = (
        await db.execute(
            select(func.count()).select_from(WorkflowRun).where(
                WorkflowRun.assignee_id == user.id,
                WorkflowRun.status.in_([RunStatus.queued, RunStatus.starting, RunStatus.running]),
            )
        )
    ).scalar_one()
    machines = (
        await db.execute(
            select(Machine).where(Machine.user_id == user.id, Machine.kind == "laptop", Machine.revoked_at.is_(None))
        )
    ).scalars().all()
    online = [m for m in machines if m.last_seen_at and (runs.now() - m.last_seen_at).total_seconds() < 90]
    return {
        "offered": offered,
        "active": active,
        "dispatch_mode": user.dispatch_mode.value,
        "machines": [
            {"id": m.id, "name": m.name, "platform": m.platform, "last_seen_at": m.last_seen_at, "online": m in online}
            for m in machines
        ],
    }


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(body: TaskIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    assignee = await db.get(User, body.assignee_id)
    if assignee is None or not await runs.assignable(db, user, assignee):
        raise HTTPException(403, "You cannot assign work to that person")
    repo = runs.validate_repo(body.repo, for_ai=assignee.kind == UserKind.ai)
    if assignee.kind == UserKind.ai and not repo:
        raise HTTPException(422, "AI developers need a repository to work in")
    base_branch = runs.validate_branch(body.base_branch)
    run = await runs.create_run(
        db,
        org_id=user.org_id,
        assignee=assignee,
        title=body.title.strip(),
        prompt=body.prompt.strip(),
        repo=repo,
        base_branch=base_branch,
        task_ref=(body.task_ref or "").strip() or None,
        mode=body.mode,
        permission_profile=body.permission_profile,
        trigger="assigned",
        triggered_by=user,
    )
    await db.commit()
    return task_out(await load_run(db, user, run.id))


@router.get("/{run_id}", response_model=TaskOut)
async def get_task(run_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return task_out(await load_run(db, user, run_id))


@router.post("/{run_id}/accept", response_model=TaskOut)
async def accept_task(
    run_id: uuid.UUID, body: AcceptIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    run = await load_run(db, user, run_id)
    await runs.accept(db, run, user, body.interactive)
    await db.commit()
    return task_out(await load_run(db, user, run_id))


@router.post("/{run_id}/decline", response_model=TaskOut)
async def decline_task(
    run_id: uuid.UUID, body: DeclineIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    run = await load_run(db, user, run_id)
    await runs.decline(db, run, user, body.reason)
    await db.commit()
    return task_out(await load_run(db, user, run_id))


@router.post("/{run_id}/cancel", response_model=TaskOut)
async def cancel_task(run_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    run = await load_run(db, user, run_id)
    allowed = user.role.value == "admin" or run.triggered_by_id == user.id or run.assignee_id == user.id
    if not allowed and run.assignee is not None:
        allowed = await runs.assignable(db, user, run.assignee) and user.role.value == "lead"
    if not allowed:
        raise HTTPException(403, "Only the assignee, the person who created it, a lead or an admin can cancel")
    await runs.cancel(db, run, user)
    await db.commit()
    return task_out(await load_run(db, user, run_id))


@router.post("/{run_id}/retry", response_model=TaskOut, status_code=201)
async def retry_task(run_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    run = await load_run(db, user, run_id)
    if run.assignee is None or not await runs.assignable(db, user, run.assignee):
        raise HTTPException(403, "You cannot assign work to that person")
    new = await runs.retry(db, run, user)
    await db.commit()
    return task_out(await load_run(db, user, new.id))


@router.post("/{run_id}/complete", response_model=TaskOut)
async def complete_task(run_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """The assignee marks an interactive task done (the agent cannot know when a person is finished)."""
    run = await load_run(db, user, run_id)
    if run.assignee_id != user.id:
        raise HTTPException(403, "Only the assignee can mark this task done")
    if run.status not in ACTIVE_RUN_STATUSES:
        raise HTTPException(409, f"This task is {run.status.value}")
    await runs.report(db, run, RunStatus.succeeded, actor=user)
    await db.commit()
    return task_out(await load_run(db, user, run_id))
