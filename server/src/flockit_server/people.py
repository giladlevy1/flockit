from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Set

from flockit_server.models import Role, User
from flockit_server.schemas import TeamRef, UserOut


def user_out(
    user: User,
    session_count: int = 0,
    last_session_at: Optional[datetime] = None,
    visible_team_ids: Optional[Set[uuid.UUID]] = None,
) -> UserOut:
    """``visible_team_ids`` limits which of the user's teams are named; ``None`` shows all."""
    teams = [t for t in user.teams if visible_team_ids is None or t.id in visible_team_ids]
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        is_active=user.is_active,
        teams=sorted((TeamRef(id=t.id, name=t.name) for t in teams), key=lambda t: t.name),
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        session_count=session_count,
        last_session_at=last_session_at,
    )


def visible_team_ids(viewer: User) -> Optional[Set[uuid.UUID]]:
    """Teams whose names this viewer may see: all for admins, their own otherwise."""
    if viewer.role == Role.admin:
        return None
    return {t.id for t in viewer.teams}
