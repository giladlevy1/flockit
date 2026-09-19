"""People and teams. Anyone can list the people in their scope; only admins change anything."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server.db import get_db
from flockit_server.deps import current_user, require_admin
from flockit_server.models import AgentSession, LoginSession, Role, Team, User, UserKind
from flockit_server.people import user_out, visible_team_ids
from flockit_server.schemas import TeamIn, TeamOut, UserCreate, UserOut, UserUpdate
from flockit_server.scope import visible_users
from flockit_server.security import hash_password

router = APIRouter(prefix="/api", tags=["people"])


async def _teams(db: AsyncSession, org_id: uuid.UUID, ids: List[uuid.UUID]) -> List[Team]:
    if not ids:
        return []
    found = (await db.execute(select(Team).where(Team.org_id == org_id, Team.id.in_(ids)))).scalars().all()
    if len(found) != len(set(ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown team")
    return list(found)


async def _users(db: AsyncSession, org_id: uuid.UUID, ids: List[uuid.UUID]) -> List[User]:
    if not ids:
        return []
    found = (await db.execute(select(User).where(User.org_id == org_id, User.id.in_(ids)))).scalars().all()
    if len(found) != len(set(ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown user")
    return list(found)


async def _admin_count(db: AsyncSession, org_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(User).where(User.org_id == org_id, User.role == Role.admin, User.is_active)
        )
    ).scalar_one()


@router.get("/users", response_model=List[UserOut])
async def list_users(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    stats = (
        select(AgentSession.human_owner_id, func.count().label("n"), func.max(AgentSession.started_at).label("last"))
        .group_by(AgentSession.human_owner_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(User, stats.c.n, stats.c.last)
            .outerjoin(stats, stats.c.human_owner_id == User.id)
            .where(visible_users(user), User.kind == UserKind.human)
            .order_by(User.name)
        )
    ).all()
    teams = visible_team_ids(user)
    return [user_out(u, n or 0, last, teams) for u, n, last in rows]


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    user = User(
        org_id=admin.org_id,
        email=body.email,
        name=body.name.strip(),
        role=body.role,
        password_hash=hash_password(body.password),
    )
    user.teams = await _teams(db, admin.org_id, body.team_ids)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Someone with that email already exists") from exc
    await db.refresh(user)
    return user_out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    user = (await db.execute(select(User).where(User.id == user_id, User.org_id == admin.org_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "User not found")
    demoting = body.role is not None and body.role != Role.admin and user.role == Role.admin
    deactivating = body.is_active is False and user.role == Role.admin
    if (demoting or deactivating) and await _admin_count(db, admin.org_id) <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Keep at least one active admin")
    if body.name is not None:
        user.name = body.name.strip()
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            # Sign them out everywhere. Their collector tokens stop working via the is_active check.
            await db.execute(LoginSession.__table__.delete().where(LoginSession.user_id == user.id))
    if body.team_ids is not None:
        user.teams = await _teams(db, admin.org_id, body.team_ids)
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        # A reset means the old credentials are no longer trusted: sign them out everywhere.
        await db.execute(LoginSession.__table__.delete().where(LoginSession.user_id == user.id))
    await db.commit()
    await db.refresh(user)
    return user_out(user)


def _team_out(team: Team, viewer: User | None = None) -> TeamOut:
    """Members are listed only when the viewer may see them (admins and leads; a developer sees just themselves)."""
    members = team.members
    if viewer is not None and viewer.role == Role.developer:
        members = [m for m in members if m.id == viewer.id]
    return TeamOut(id=team.id, name=team.name, member_ids=[m.id for m in members])


@router.get("/teams", response_model=List[TeamOut])
async def list_teams(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    q = select(Team).where(Team.org_id == user.org_id).order_by(Team.name)
    teams = (await db.execute(q)).scalars().all()
    if user.role != Role.admin:
        teams = [t for t in teams if any(m.id == user.id for m in t.members)]
    return [_team_out(t, user) for t in teams]


@router.post("/teams", response_model=TeamOut, status_code=201)
async def create_team(body: TeamIn, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    team = Team(org_id=admin.org_id, name=body.name.strip())
    team.members = await _users(db, admin.org_id, body.member_ids or [])
    db.add(team)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A team with that name already exists") from exc
    await db.refresh(team)
    return _team_out(team)


@router.patch("/teams/{team_id}", response_model=TeamOut)
async def update_team(
    team_id: uuid.UUID, body: TeamIn, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    team = (await db.execute(select(Team).where(Team.id == team_id, Team.org_id == admin.org_id))).scalar_one_or_none()
    if team is None:
        raise HTTPException(404, "Team not found")
    team.name = body.name.strip()
    if body.member_ids is not None:
        team.members = await _users(db, admin.org_id, body.member_ids)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A team with that name already exists") from exc
    await db.refresh(team)
    return _team_out(team)


@router.delete("/teams/{team_id}", status_code=204)
async def delete_team(team_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    team = (await db.execute(select(Team).where(Team.id == team_id, Team.org_id == admin.org_id))).scalar_one_or_none()
    if team is None:
        raise HTTPException(404, "Team not found")
    await db.delete(team)
    await db.commit()
