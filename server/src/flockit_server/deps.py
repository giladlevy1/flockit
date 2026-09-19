"""Request authentication.

Two credentials exist:
- A **login cookie** for people using the web UI. Mutating requests must also send
  ``X-Flockit-Request: 1``; browsers cannot add that header cross-origin without a
  CORS preflight, which this server never grants, so it doubles as CSRF protection.
- A **collector token** (``Authorization: Bearer flk_...``) for ingest only. Each
  token belongs to one person, which is how every session gets its human owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server.db import get_db
from flockit_server.models import ApiToken, LoginSession, Role, User
from flockit_server.security import hash_token

COOKIE_NAME = "flockit_session"
CSRF_HEADER = "x-flockit-request"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _bearer_user(request: Request, db: AsyncSession) -> Optional[User]:
    """An MCP token acts as its owner, with exactly their role scope. Collector and
    per-task tokens are refused here: writing sessions is not permission to read them."""
    scheme, _, raw = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not raw.strip():
        return None
    found = (
        await db.execute(
            select(ApiToken, User)
            .join(User, User.id == ApiToken.user_id)
            .where(
                ApiToken.token_hash == hash_token(raw.strip()),
                ApiToken.kind == "mcp",
                ApiToken.run_id.is_(None),
                ApiToken.revoked_at.is_(None),
                or_(ApiToken.expires_at.is_(None), ApiToken.expires_at > _now()),
            )
        )
    ).first()
    if found is None or not found[1].is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked token")
    api_token, user = found
    now = _now()
    if api_token.last_used_at is None or now - api_token.last_used_at > timedelta(minutes=1):
        await db.execute(update(ApiToken).where(ApiToken.id == api_token.id).values(last_used_at=now))
        await db.commit()
    return user


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    bearer = await _bearer_user(request, db)
    if bearer is not None:
        return bearer
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing X-Flockit-Request header")
    row = (
        await db.execute(
            select(User)
            .join(LoginSession, LoginSession.user_id == User.id)
            .where(LoginSession.token_hash == hash_token(token), LoginSession.expires_at > _now())
        )
    ).scalar_one_or_none()
    if row is None or not row.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    return row


async def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only")
    return user


@dataclass
class CollectorIdentity:
    user: User
    token_id: object
    run_id: object = None  # set for an AI developer's per-task token


async def collector_identity(request: Request, db: AsyncSession = Depends(get_db)) -> CollectorIdentity:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing collector token")
    found: Optional[tuple[ApiToken, User]] = (
        await db.execute(
            select(ApiToken, User)
            .join(User, User.id == ApiToken.user_id)
            .where(
                ApiToken.token_hash == hash_token(token.strip()),
                ApiToken.revoked_at.is_(None),
                or_(ApiToken.expires_at.is_(None), ApiToken.expires_at > _now()),
            )
        )
    ).first()
    if found is None or not found[1].is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked collector token")
    api_token, user = found
    if api_token.kind != "collector":
        # An editor token may read; it may not write sessions as this person.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This token cannot send sessions")
    if api_token.run_id is not None:
        from flockit_server.models import RunStatus, WorkflowRun

        run = await db.get(WorkflowRun, api_token.run_id)
        if run is None or run.status in (RunStatus.succeeded, RunStatus.failed, RunStatus.cancelled, RunStatus.declined):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This task has ended")
    now = _now()
    if api_token.last_used_at is None or now - api_token.last_used_at > timedelta(minutes=1):
        await db.execute(update(ApiToken).where(ApiToken.id == api_token.id).values(last_used_at=now))
        await db.commit()
    return CollectorIdentity(user=user, token_id=api_token.id, run_id=api_token.run_id)
