"""Workflows: reusable task definitions with manual, scheduled and webhook triggers.

A webhook URL embeds a random secret (``/api/hooks/<secret>``); only its hash is
stored. Any system that can POST JSON can trigger a workflow: Jira, Linear, Sentry,
PagerDuty, GitHub, Zendesk. Inbound only; Flockit never calls out.
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime
from typing import Any, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server import runs
from flockit_server.db import get_db, sessionmaker
from flockit_server.deps import current_user
from flockit_server.models import PermissionProfile, Role, RunMode, User, UserKind, Workflow, WorkflowRun
from flockit_server.routers.connect import public_url
from flockit_server.routers.tasks import TaskOut, task_out
from flockit_server.security import hash_token

router = APIRouter(tags=["workflows"])

MAX_WEBHOOK_BYTES = 256 * 1024


class _Budget:
    """Deliveries per workflow per hour, in process memory (one app container)."""

    def __init__(self) -> None:
        self.hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        import time

        from flockit_server.settings import get_settings

        now_s = time.monotonic()
        recent = [t for t in self.hits.get(key, []) if now_s - t < 3600]
        if len(recent) >= get_settings().webhook_rate_per_hour:
            self.hits[key] = recent
            return False
        recent.append(now_s)
        self.hits[key] = recent
        return True


_webhook_budget = _Budget()


def next_run(cron: str, tz: str, after: Optional[datetime] = None) -> datetime:
    zone = ZoneInfo(tz)
    base = (after or runs.now()).astimezone(zone)
    return croniter(cron, base).get_next(datetime)


class WorkflowIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=4000)
    prompt_template: str = Field(min_length=1, max_length=50_000)
    repo: str = Field(min_length=1, max_length=300)
    base_branch: Optional[str] = Field(default=None, max_length=200)
    assignee_id: uuid.UUID
    mode: RunMode = RunMode.ask
    permission_profile: PermissionProfile = PermissionProfile.edit
    schedule_cron: Optional[str] = Field(default=None, max_length=120)
    schedule_timezone: str = Field(default="UTC", max_length=64)
    webhook_enabled: bool = False
    webhook_filter: Optional[Any] = None
    enabled: bool = True

    @field_validator("schedule_cron")
    @classmethod
    def _cron(cls, v: Optional[str]) -> Optional[str]:
        v = (v or "").strip() or None
        if v and not croniter.is_valid(v):
            raise ValueError("Not a valid cron expression (for example: 0 9 * * 1-5)")
        return v

    @field_validator("schedule_timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown time zone") from exc
        return v

    @field_validator("webhook_filter")
    @classmethod
    def _filter(cls, v: Any) -> Any:
        if v in (None, "", {}, []):
            return None
        rules = v if isinstance(v, list) else [v]
        for rule in rules:
            if not isinstance(rule, dict) or not isinstance(rule.get("path"), str):
                raise ValueError('Each filter needs a "path", plus "equals" or "contains"')
            if "equals" not in rule and "contains" not in rule:
                raise ValueError('Each filter needs "equals" or "contains"')
        if len(json.dumps(v)) > 4000:
            raise ValueError("Filter is too large")
        return v


class WorkflowOut(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    prompt_template: str
    repo: str
    base_branch: Optional[str]
    assignee: dict
    mode: RunMode
    permission_profile: PermissionProfile
    schedule_cron: Optional[str]
    schedule_timezone: str
    next_run_at: Optional[datetime]
    webhook_enabled: bool
    webhook_filter: Optional[Any]
    enabled: bool
    created_at: datetime
    last_run_at: Optional[datetime]
    runs: dict
    webhook_url: Optional[str] = None  # only in the response that creates or rotates the secret


async def _out(db: AsyncSession, wf: Workflow, webhook_url: Optional[str] = None) -> WorkflowOut:
    counts = {
        s.value: n
        for s, n in (
            await db.execute(
                select(WorkflowRun.status, func.count()).where(WorkflowRun.workflow_id == wf.id).group_by(WorkflowRun.status)
            )
        ).all()
    }
    return WorkflowOut(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        prompt_template=wf.prompt_template,
        repo=wf.repo,
        base_branch=wf.base_branch,
        assignee={"id": wf.assignee.id, "name": wf.assignee.name, "kind": wf.assignee.kind.value},
        mode=wf.mode,
        permission_profile=wf.permission_profile,
        schedule_cron=wf.schedule_cron,
        schedule_timezone=wf.schedule_timezone,
        next_run_at=wf.next_run_at,
        webhook_enabled=wf.webhook_enabled,
        webhook_filter=wf.webhook_filter,
        enabled=wf.enabled,
        created_at=wf.created_at,
        last_run_at=wf.last_run_at,
        runs=counts,
        webhook_url=webhook_url,
    )


def _can_manage(user: User) -> None:
    if user.role not in (Role.admin, Role.lead):
        raise HTTPException(403, "Only leads and admins manage workflows")


async def _load(db: AsyncSession, user: User, workflow_id: uuid.UUID) -> Workflow:
    wf = (
        await db.execute(select(Workflow).where(Workflow.id == workflow_id, Workflow.org_id == user.org_id))
    ).scalar_one_or_none()
    if wf is None:
        raise HTTPException(404, "Workflow not found")
    return wf


async def _may_change(db: AsyncSession, user: User, wf: Workflow) -> None:
    """Admins change any workflow; a lead only workflows whose current assignee they could assign to."""
    _can_manage(user)
    if user.role != Role.admin and not await runs.assignable(db, user, wf.assignee):
        raise HTTPException(403, "This workflow sends work to someone outside your teams")


async def _apply(db: AsyncSession, user: User, wf: Workflow, body: WorkflowIn) -> None:
    assignee = await db.get(User, body.assignee_id)
    if assignee is None or not await runs.assignable(db, user, assignee):
        raise HTTPException(403, "You cannot assign work to that person")
    repo = runs.validate_repo(body.repo, for_ai=assignee.kind == UserKind.ai)
    if not repo:
        raise HTTPException(422, "A workflow needs a repository")
    wf.name = body.name.strip()
    wf.description = (body.description or "").strip() or None
    wf.prompt_template = body.prompt_template
    wf.repo = repo
    wf.base_branch = runs.validate_branch(body.base_branch)
    wf.assignee_id = assignee.id
    wf.mode = body.mode
    wf.permission_profile = body.permission_profile
    wf.schedule_cron = body.schedule_cron
    wf.schedule_timezone = body.schedule_timezone
    wf.next_run_at = next_run(body.schedule_cron, body.schedule_timezone) if body.schedule_cron and body.enabled else None
    wf.webhook_enabled = body.webhook_enabled
    wf.webhook_filter = body.webhook_filter
    wf.enabled = body.enabled


def _new_secret() -> tuple[str, str]:
    secret = "whk_" + secrets.token_urlsafe(32)
    return secret, hash_token(secret)


@router.get("/api/workflows", response_model=List[WorkflowOut])
async def list_workflows(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(Workflow).where(Workflow.org_id == user.org_id).order_by(Workflow.name))
    ).scalars().unique().all()
    if user.role != Role.admin:
        # Only workflows that send work to people (or AI developers) this person can see.
        rows = [wf for wf in rows if await runs.assignable(db, user, wf.assignee)]
    return [await _out(db, wf) for wf in rows]


@router.post("/api/workflows", response_model=WorkflowOut, status_code=201)
async def create_workflow(
    body: WorkflowIn, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    _can_manage(user)
    wf = Workflow(org_id=user.org_id, created_by_id=user.id, name="", prompt_template="", repo="", assignee_id=user.id)
    await _apply(db, user, wf, body)
    url = None
    if body.webhook_enabled:
        secret, wf.webhook_secret_hash = _new_secret()
        url = f"{(await public_url(request, db))[0]}/api/hooks/{secret}"
    db.add(wf)
    await db.flush()
    await runs.audit(db, user.org_id, user, "workflow.created", "workflow", wf.id, {"name": wf.name})
    await db.commit()
    return await _out(db, await _load(db, user, wf.id), url)


@router.get("/api/workflows/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(workflow_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf = await _load(db, user, workflow_id)
    if user.role != Role.admin and not await runs.assignable(db, user, wf.assignee):
        raise HTTPException(404, "Workflow not found")
    return await _out(db, wf)


@router.put("/api/workflows/{workflow_id}", response_model=WorkflowOut)
async def update_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowIn,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    wf = await _load(db, user, workflow_id)
    await _may_change(db, user, wf)
    await _apply(db, user, wf, body)
    url = None
    if body.webhook_enabled and not wf.webhook_secret_hash:
        secret, wf.webhook_secret_hash = _new_secret()
        url = f"{(await public_url(request, db))[0]}/api/hooks/{secret}"
    await runs.audit(db, user.org_id, user, "workflow.updated", "workflow", wf.id, {"name": wf.name})
    await db.commit()
    return await _out(db, await _load(db, user, wf.id), url)


@router.post("/api/workflows/{workflow_id}/webhook-secret", response_model=WorkflowOut)
async def rotate_webhook_secret(
    workflow_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    wf = await _load(db, user, workflow_id)
    await _may_change(db, user, wf)
    secret, wf.webhook_secret_hash = _new_secret()
    wf.webhook_enabled = True
    await runs.audit(db, user.org_id, user, "workflow.webhook_rotated", "workflow", wf.id)
    await db.commit()
    return await _out(db, wf, f"{(await public_url(request, db))[0]}/api/hooks/{secret}")


@router.delete("/api/workflows/{workflow_id}", status_code=204)
async def delete_workflow(workflow_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf = await _load(db, user, workflow_id)
    await _may_change(db, user, wf)
    await runs.audit(db, user.org_id, user, "workflow.deleted", "workflow", wf.id, {"name": wf.name})
    await db.delete(wf)
    await db.commit()


class RunNowIn(BaseModel):
    payload: Optional[dict] = None


async def start_workflow(
    db: AsyncSession, wf: Workflow, trigger: str, payload: Optional[dict], triggered_by: Optional[User]
) -> WorkflowRun:
    assignee = wf.assignee
    if not assignee.is_active:
        raise HTTPException(409, f"{assignee.name} is deactivated; pick another assignee")
    context = {"payload": payload or {}, "workflow": {"name": wf.name}, "now": runs.now().isoformat()}
    title = runs.render(wf.name, context)
    if payload:
        headline = next(
            (runs.lookup(payload, p) for p in ("issue.title", "ticket.subject", "title", "subject", "summary")
             if isinstance(runs.lookup(payload, p), str)),
            None,
        )
        if headline:
            title = f"{wf.name}: {headline}"
    ref = None
    if payload:
        for path in ("issue.html_url", "ticket.url", "url", "issue.key", "key"):
            value = runs.lookup(payload, path)
            if isinstance(value, str) and value:
                ref = value[:300]
                break
    # A webhook body is written by whoever can file a ticket. It must never start an agent
    # on a person's machine unattended: webhook work for people always waits for them to accept.
    # (AI developers run in disposable sandboxes on runners, so they still start on their own.)
    mode = runs.untrusted_mode(trigger, assignee, wf.mode)
    run = await runs.create_run(
        db,
        org_id=wf.org_id,
        assignee=assignee,
        title=title,
        prompt=runs.render(wf.prompt_template, context),
        repo=wf.repo,
        base_branch=wf.base_branch,
        task_ref=ref,
        mode=mode,
        permission_profile=wf.permission_profile,
        trigger=trigger,
        trigger_payload=payload,
        triggered_by=triggered_by,
        workflow=wf,
    )
    wf.last_run_at = runs.now()
    return run


@router.post("/api/workflows/{workflow_id}/run", response_model=TaskOut, status_code=201)
async def run_now(
    workflow_id: uuid.UUID, body: RunNowIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    wf = await _load(db, user, workflow_id)
    if not await runs.assignable(db, user, wf.assignee):
        raise HTTPException(403, "You cannot assign work to this workflow's assignee")
    run = await start_workflow(db, wf, "manual", body.payload, user)
    await db.commit()
    from flockit_server.routers.tasks import load_run

    return task_out(await load_run(db, user, run.id))


@router.post("/api/hooks/{secret}", status_code=202)
async def webhook(secret: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Trigger a workflow from any system. The secret in the URL is the credential."""
    if not secret.startswith("whk_") or len(secret) > 100:
        raise HTTPException(404, "Not found")
    wf = (
        await db.execute(
            select(Workflow).where(Workflow.webhook_secret_hash == hash_token(secret), Workflow.webhook_enabled)
        )
    ).scalar_one_or_none()
    if wf is None:
        raise HTTPException(404, "Not found")
    if not _webhook_budget.allow(str(wf.id)):
        raise HTTPException(429, "Too many deliveries for this workflow; try again later")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_WEBHOOK_BYTES:
            raise HTTPException(413, "Payload too large")
        chunks.append(chunk)
    try:
        payload = json.loads(b"".join(chunks) or b"{}")
    except (ValueError, RecursionError) as exc:
        raise HTTPException(400, "Body must be JSON") from exc
    if not isinstance(payload, dict):
        payload = {"body": payload}
    if not wf.enabled:
        return {"accepted": False, "reason": "workflow is disabled"}
    if not runs.matches_filter(payload, wf.webhook_filter):
        return {"accepted": False, "reason": "filter did not match"}
    run = await start_workflow(db, wf, "webhook", payload, None)
    await db.commit()
    return {"accepted": True, "task_id": str(run.id)}


async def run_due_schedules() -> int:
    """Start every scheduled workflow whose time has come. Safe with several app replicas:
    a transaction-level advisory lock lets only one of them schedule at a time."""
    started = 0
    async with sessionmaker()() as db:
        locked = (await db.execute(text("select pg_try_advisory_xact_lock(4652103)"))).scalar_one()
        if not locked:
            return 0
        due = (
            await db.execute(
                select(Workflow)
                .where(Workflow.enabled, Workflow.schedule_cron.is_not(None), Workflow.next_run_at <= runs.now())
                .with_for_update(skip_locked=True, of=Workflow)
            )
        ).scalars().unique().all()
        for wf in due:
            try:
                if wf.assignee.is_active:
                    await start_workflow(db, wf, "schedule", None, None)
                    started += 1
            finally:
                wf.next_run_at = next_run(wf.schedule_cron, wf.schedule_timezone)  # type: ignore[arg-type]
        await db.commit()
    return started
