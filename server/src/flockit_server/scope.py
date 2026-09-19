"""Role scoping. Every query that returns sessions or people goes through here.

- admin:     the whole organisation
- lead:      themselves plus every member of every team they belong to
- developer: themselves
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import aliased

from flockit_server.models import AgentSession, Role, TeamMember, User

SCOPE_LABELS = {Role.admin: "organisation", Role.lead: "team", Role.developer: "self"}


def _teammates(user: User):
    mine = aliased(TeamMember)
    theirs = aliased(TeamMember)
    return select(theirs.user_id).join(mine, mine.team_id == theirs.team_id).where(mine.user_id == user.id)


def visible_users(user: User) -> ColumnElement[bool]:
    """A WHERE clause over ``User`` rows this user may see."""
    if user.role == Role.admin:
        return User.org_id == user.org_id
    if user.role == Role.lead:
        return (User.org_id == user.org_id) & or_(User.id == user.id, User.id.in_(_teammates(user)))
    return User.id == user.id


def visible_sessions(user: User) -> ColumnElement[bool]:
    """A WHERE clause over ``AgentSession`` rows this user may see."""
    if user.role == Role.admin:
        return AgentSession.org_id == user.org_id
    if user.role == Role.lead:
        return (AgentSession.org_id == user.org_id) & or_(
            AgentSession.human_owner_id == user.id, AgentSession.human_owner_id.in_(_teammates(user))
        )
    return AgentSession.human_owner_id == user.id
