from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server import ratelimit
from flockit_server.db import get_db
from flockit_server.deps import COOKIE_NAME, current_user
from flockit_server.models import LoginSession, Organization, Role, User
from flockit_server.people import user_out
from flockit_server.routers.connect import safe_url
from flockit_server.schemas import LoginIn, MeOut, OrgOut, PasswordChange, SetupIn
from flockit_server.scope import SCOPE_LABELS
from flockit_server.security import hash_password, hash_token, new_login_token, verify_password
from flockit_server.settings import get_settings

router = APIRouter(prefix="/api", tags=["auth"])


async def _start_login(db: AsyncSession, response: Response, user: User) -> None:
    settings = get_settings()
    token, token_hash = new_login_token()
    now = datetime.now(timezone.utc)
    db.add(LoginSession(user_id=user.id, token_hash=token_hash, expires_at=now + timedelta(hours=settings.login_ttl_hours)))
    user.last_login_at = now
    # Housekeeping: expired logins are useless, drop them.
    await db.execute(delete(LoginSession).where(LoginSession.expires_at < now))
    await db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.login_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path="/",
    )


@router.get("/setup")
async def setup_status(db: AsyncSession = Depends(get_db)) -> dict:
    count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    return {"needs_setup": count == 0}


@router.post("/setup", status_code=status.HTTP_201_CREATED)
async def setup(body: SetupIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    """First run only: create the organisation and its first admin.

    The address the admin used is recorded as the organisation's public URL, so later
    install commands never depend on an arbitrary request's Host header.
    """
    # Serialise concurrent first-run requests.
    await db.execute(select(func.pg_advisory_xact_lock(0x464C4F434B)))
    if (await db.execute(select(func.count()).select_from(User))).scalar_one() > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Flockit is already set up")
    org = Organization(name=body.org_name.strip(), public_url=safe_url(str(request.base_url)))
    db.add(org)
    await db.flush()
    user = User(
        org_id=org.id,
        email=body.email,
        name=body.name.strip(),
        role=Role.admin,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.flush()
    await _start_login(db, response, user)
    return {"ok": True}


@router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    client = request.client.host if request.client else "unknown"
    wait = ratelimit.by_email.retry_after(body.email) or ratelimit.by_client.retry_after(client)
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed sign-ins. Try again in a few minutes.",
            headers={"Retry-After": str(wait)},
        )
    user = (await db.execute(select(User).where(User.email == body.email).limit(1))).scalar_one_or_none()
    if not verify_password(user.password_hash if user else None, body.password) or user is None or not user.is_active:
        ratelimit.by_email.fail(body.email)
        ratelimit.by_client.fail(client)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    ratelimit.by_email.reset(body.email)
    await _start_login(db, response, user)
    return {"ok": True}


@router.post("/auth/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        await db.execute(delete(LoginSession).where(LoginSession.token_hash == hash_token(token)))
        await db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me", response_model=MeOut)
async def me(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> MeOut:
    org = await db.get(Organization, user.org_id)
    assert org is not None
    return MeOut(user=user_out(user), org=OrgOut(id=org.id, name=org.name), scope=SCOPE_LABELS[user.role])


@router.post("/auth/password")
async def change_password(
    body: PasswordChange, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    # Sign out every other browser: a stolen cookie must not outlive a password change.
    current = hash_token(request.cookies.get(COOKIE_NAME, ""))
    await db.execute(delete(LoginSession).where(LoginSession.user_id == user.id, LoginSession.token_hash != current))
    await db.commit()
    return {"ok": True}
