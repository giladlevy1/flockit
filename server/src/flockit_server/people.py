from __future__ import annotations

from datetime import datetime
from typing import Optional

from flockit_server.models import User
from flockit_server.schemas import TeamRef, UserOut


def user_out(user: User, session_count: int = 0, last_session_at: Optional[datetime] = None) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        is_active=user.is_active,
        teams=sorted((TeamRef(id=t.id, name=t.name) for t in user.teams), key=lambda t: t.name),
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        session_count=session_count,
        last_session_at=last_session_at,
    )
