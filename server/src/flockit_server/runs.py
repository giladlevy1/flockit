"""Tasks: creating them, moving them through their lifecycle, and who may do what.

Lifecycle::

    offered --accept--> queued --claim--> starting --session starts--> running --> succeeded | failed
       |                   ^
       +--decline--> declined        (any active state) --cancel--> cancelled

- A task for an AI developer is queued immediately; a runner claims it.
- A task for a person is *offered* unless the workflow is set to auto-start and the
  person allows auto-start, in which case it is queued and their laptop agent starts
  it headless. Accepting an offered task queues it as *interactive*: the agent opens a
  terminal with Claude Code already working on it.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server.models import (
    ACTIVE_RUN_STATUSES,
    AuditEvent,
    DispatchMode,
    PermissionProfile,
    Role,
    RunMode,
    RunStatus,
    User,
    UserKind,
    Workflow,
    WorkflowRun,
)
from flockit_server.scope import visible_users


def now() -> datetime:
    return datetime.now(timezone.utc)


async def audit(
    db: AsyncSession,
    org_id: uuid.UUID,
    actor: Optional[User],
    action: str,
    target_type: Optional[str] = None,
    target_id: Any = None,
    detail: Optional[dict] = None,
) -> None:
    db.add(
        AuditEvent(
            org_id=org_id,
            actor_id=actor.id if actor else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail=detail,
        )
    )


# --- Who may assign work to whom ----------------------------------------------


async def assignable(db: AsyncSession, viewer: User, assignee: User) -> bool:
    """Admins assign to anyone. Everyone may assign to themselves and to any AI developer.
    Leads may assign to the people on their teams."""
    if assignee.org_id != viewer.org_id or not assignee.is_active:
        return False
    if viewer.role == Role.admin or assignee.id == viewer.id or assignee.kind == UserKind.ai:
        return True
    if viewer.role == Role.lead:
        found = (await db.execute(select(User.id).where(User.id == assignee.id, visible_users(viewer)))).first()
        return found is not None
    return False


def visible_runs(viewer: User):
    """Admins see every task. Others see tasks assigned to or created by people they can see."""
    if viewer.role == Role.admin:
        return WorkflowRun.org_id == viewer.org_id
    people = select(User.id).where(visible_users(viewer))
    ai_mine = select(User.id).where(User.kind == UserKind.ai, User.sponsor_id == viewer.id)
    return and_(
        WorkflowRun.org_id == viewer.org_id,
        or_(
            WorkflowRun.assignee_id.in_(people),
            WorkflowRun.triggered_by_id.in_(people),
            WorkflowRun.assignee_id.in_(ai_mine),
        ),
    )


# --- Creating tasks ------------------------------------------------------------

_SLUG = re.compile(r"[^a-z0-9]+")


def branch_for(run_id: uuid.UUID, title: str) -> str:
    slug = _SLUG.sub("-", title.lower()).strip("-")[:40].strip("-") or "task"
    return f"flockit/{str(run_id)[:8]}-{slug}"


def initial_status(assignee: User, mode: RunMode) -> RunStatus:
    if assignee.kind == UserKind.ai:
        return RunStatus.queued
    if mode == RunMode.auto and assignee.dispatch_mode == DispatchMode.auto:
        return RunStatus.queued
    return RunStatus.offered


async def create_run(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assignee: User,
    title: str,
    prompt: str,
    repo: Optional[str],
    base_branch: Optional[str] = None,
    task_ref: Optional[str] = None,
    mode: RunMode = RunMode.ask,
    permission_profile: PermissionProfile = PermissionProfile.edit,
    trigger: str = "manual",
    trigger_payload: Optional[dict] = None,
    triggered_by: Optional[User] = None,
    workflow: Optional[Workflow] = None,
) -> WorkflowRun:
    run_id = uuid.uuid4()
    status = initial_status(assignee, mode)
    run = WorkflowRun(
        id=run_id,
        org_id=org_id,
        workflow_id=workflow.id if workflow else None,
        title=title[:300],
        prompt=prompt,
        repo=repo,
        base_branch=base_branch,
        branch=branch_for(run_id, title),
        task_ref=task_ref,
        assignee_id=assignee.id,
        mode=mode,
        permission_profile=permission_profile,
        status=status,
        # Auto-started work runs headless; anything a person accepts opens interactively.
        interactive=False,
        trigger=trigger,
        trigger_payload=trigger_payload,
        triggered_by_id=triggered_by.id if triggered_by else None,
    )
    db.add(run)
    await db.flush()
    await audit(
        db,
        org_id,
        triggered_by,
        "task.created",
        "task",
        run.id,
        {"title": run.title, "assignee": assignee.name, "trigger": trigger, "status": status.value},
    )
    return run


# --- Transitions ---------------------------------------------------------------


def _require(run: WorkflowRun, *allowed: RunStatus) -> None:
    if run.status not in allowed:
        raise HTTPException(409, f"This task is {run.status.value}")


async def accept(db: AsyncSession, run: WorkflowRun, user: User, interactive: bool = True) -> None:
    if run.assignee_id != user.id:
        raise HTTPException(403, "Only the assignee can accept this task")
    _require(run, RunStatus.offered)
    run.status = RunStatus.queued
    run.interactive = interactive
    run.accepted_at = now()
    await audit(db, run.org_id, user, "task.accepted", "task", run.id, {"interactive": interactive})


async def decline(db: AsyncSession, run: WorkflowRun, user: User, reason: Optional[str] = None) -> None:
    if run.assignee_id != user.id:
        raise HTTPException(403, "Only the assignee can decline this task")
    _require(run, RunStatus.offered, RunStatus.queued)
    run.status = RunStatus.declined
    run.ended_at = now()
    run.error = (reason or "")[:2000] or None
    await audit(db, run.org_id, user, "task.declined", "task", run.id, {"reason": reason})


async def cancel(db: AsyncSession, run: WorkflowRun, user: User) -> None:
    _require(run, *ACTIVE_RUN_STATUSES)
    run.status = RunStatus.cancelled
    run.ended_at = now()
    await audit(db, run.org_id, user, "task.cancelled", "task", run.id)


async def retry(db: AsyncSession, run: WorkflowRun, user: User) -> WorkflowRun:
    """A fresh task with the same definition. The original keeps its history."""
    _require(run, RunStatus.failed, RunStatus.cancelled, RunStatus.declined, RunStatus.succeeded)
    assignee = await db.get(User, run.assignee_id) if run.assignee_id else None
    if assignee is None or not assignee.is_active:
        raise HTTPException(409, "The assignee is no longer active")
    new = await create_run(
        db,
        org_id=run.org_id,
        assignee=assignee,
        title=run.title,
        prompt=run.prompt,
        repo=run.repo,
        base_branch=run.base_branch,
        task_ref=run.task_ref,
        mode=run.mode,
        permission_profile=run.permission_profile,
        trigger="retry",
        trigger_payload={"retry_of": str(run.id)},
        triggered_by=user,
        workflow=run.workflow,
    )
    return new


_PR = re.compile(r"https://[A-Za-z0-9.\-]+/[^\s)\"'>]+/(?:pull|merge_requests)/\d+")


def find_pr_url(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _PR.search(text)
    return m.group(0)[:500] if m else None


async def report(
    db: AsyncSession,
    run: WorkflowRun,
    status: RunStatus,
    *,
    result: Optional[str] = None,
    error: Optional[str] = None,
    pr_url: Optional[str] = None,
    cost_usd: Optional[float] = None,
    actor: Optional[User] = None,
) -> None:
    """A machine reports progress. Terminal states are final; late reports are ignored."""
    if run.status in (RunStatus.succeeded, RunStatus.failed, RunStatus.cancelled, RunStatus.declined):
        return
    if status == RunStatus.running:
        run.status = RunStatus.running
        run.started_at = run.started_at or now()
        return
    if status not in (RunStatus.succeeded, RunStatus.failed):
        raise HTTPException(422, "Machines may report running, succeeded or failed")
    run.status = status
    run.ended_at = now()
    run.started_at = run.started_at or run.ended_at
    if result is not None:
        run.result = result[:50_000]
    if error is not None:
        run.error = error[:10_000]
    run.pr_url = (pr_url or find_pr_url(result) or run.pr_url or None)
    if cost_usd is not None and cost_usd >= 0:
        run.cost_usd = round(float(cost_usd), 4)
    await audit(db, run.org_id, actor, f"task.{status.value}", "task", run.id, {"pr_url": run.pr_url})


# --- Prompt rendering for workflows --------------------------------------------

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]{1,120})\s*\}\}")


def lookup(payload: Any, path: str) -> Any:
    cur = payload
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def render(template: str, context: dict) -> str:
    """``{{payload.issue.title}}``-style substitution. Plain lookup only: no expressions,
    no code. Missing values render empty; long values are truncated."""

    def sub(m: "re.Match[str]") -> str:
        value = lookup(context, m.group(1))
        if value is None:
            return ""
        text = value if isinstance(value, str) else str(value)
        return text[:4000]

    return _PLACEHOLDER.sub(sub, template)


def matches_filter(payload: Any, flt: Optional[dict]) -> bool:
    """Webhook filter: ``{"path": "action", "equals": "opened"}`` or ``{"path": ..., "contains": ...}``.
    A list of such objects must all match."""
    if not flt:
        return True
    rules = flt if isinstance(flt, list) else [flt]
    for rule in rules:
        if not isinstance(rule, dict) or "path" not in rule:
            return False
        value = lookup(payload, str(rule["path"]))
        if "equals" in rule and value != rule["equals"]:
            return False
        if "contains" in rule:
            needle = rule["contains"]
            if isinstance(value, list):
                if needle not in value and not any(isinstance(v, dict) and needle in v.values() for v in value):
                    return False
            elif not isinstance(value, str) or str(needle) not in value:
                return False
    return True
