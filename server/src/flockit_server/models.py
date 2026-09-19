"""Database schema.

M0 writes to organisation, user, team, auth tables, ``session`` and ``ingest_event``.
``fact``, ``decision``, ``retrieval`` and ``workflow_run`` exist as schema only, so
later milestones add behaviour without migrating existing data.

Every row carries ``org_id``. M0 runs one organisation per deployment, but the
column means a multi-tenant deployment later is a query change, not a rewrite.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _org() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), index=True)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


# --- Enums -------------------------------------------------------------------


class Role(str, enum.Enum):
    admin = "admin"  # sees the whole organisation, manages people and teams
    lead = "lead"  # sees every member of the teams they belong to
    developer = "developer"  # sees their own sessions


class Origin(str, enum.Enum):
    human = "human"  # a person started the session (the only value M0 writes)
    workflow = "workflow"  # reserved: a future workflow runner started it


class Outcome(str, enum.Enum):
    completed = "completed"  # the developer ended the session normally
    abandoned = "abandoned"  # no activity for the abandonment window and never ended
    errored = "errored"  # reserved for agents that report a failed end
    unknown = "unknown"  # still running, or ended for a reason we cannot classify


class FactScope(str, enum.Enum):
    repo = "repo"
    service = "service"
    org = "org"


class FactState(str, enum.Enum):
    fresh = "fresh"
    drifted = "drifted"
    dead = "dead"


class DecisionOrigin(str, enum.Enum):
    review_comment = "review_comment"
    correction = "correction"
    revert = "revert"


# --- Identity ----------------------------------------------------------------


class Organization(Base):
    __tablename__ = "organization"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()


class User(Base):
    __tablename__ = "user"
    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_user_org_email"),)

    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = _org()
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"), default=Role.developer)
    # Local auth in M0. SSO later sets auth_provider/external_subject and leaves the hash empty.
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auth_provider: Mapped[str] = mapped_column(String(50), default="local", server_default="local")
    external_subject: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = _created()
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    teams: Mapped[List["Team"]] = relationship(secondary="team_member", back_populates="members", lazy="selectin")


class Team(Base):
    __tablename__ = "team"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_team_org_name"),)

    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = _org()
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = _created()

    members: Mapped[List[User]] = relationship(secondary="team_member", back_populates="teams", lazy="selectin")


class TeamMember(Base):
    __tablename__ = "team_member"

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("team.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class LoginSession(Base):
    """A browser login. Only the SHA-256 of the cookie value is stored."""

    __tablename__ = "login_session"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApiToken(Base):
    """A collector token. Belongs to one human, which is how every session gets an owner."""

    __tablename__ = "api_token"

    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = _org()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _created()
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# --- Sessions (the only entity M0 writes) ------------------------------------


class AgentSession(Base):
    __tablename__ = "session"
    __table_args__ = (
        UniqueConstraint("org_id", "agent_vendor", "external_id", name="uq_session_external"),
        Index("ix_session_org_started", "org_id", "started_at"),
        Index("ix_session_owner_started", "human_owner_id", "started_at"),
        Index("ix_session_org_repo", "org_id", "repo"),
        Index("ix_session_open", "org_id", "last_seen_at", postgresql_where=text("ended_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = _org()
    human_owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False
    )
    origin: Mapped[Origin] = mapped_column(_enum(Origin, "session_origin"), default=Origin.human)
    workflow_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_run.id", ondelete="SET NULL"), nullable=True
    )
    external_id: Mapped[str] = mapped_column(String(128))
    agent_vendor: Mapped[str] = mapped_column(String(64))
    agent_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    agent_model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    models_used: Mapped[List[str]] = mapped_column(ARRAY(String(120)), default=list, server_default="{}")
    repo: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    branch: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    task_ref: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[Outcome] = mapped_column(_enum(Outcome, "session_outcome"), default=Outcome.unknown)
    end_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    collector_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    owner: Mapped[User] = relationship(lazy="joined", innerjoin=True)


class IngestEvent(Base):
    """Seen event ids, so collector retries are idempotent."""

    __tablename__ = "ingest_event"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("session.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    received_at: Mapped[datetime] = _created()


# --- Schema only in M0 --------------------------------------------------------


class WorkflowRun(Base):
    """Seam for a future workflow runner. Nothing writes here in M0, on purpose."""

    __tablename__ = "workflow_run"

    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = _org()
    task_ref: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    triggered_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Fact(Base):
    """M2: a verifiable environment fact. ``producing_command`` is the whole thesis."""

    __tablename__ = "fact"

    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = _org()
    claim: Mapped[str] = mapped_column(Text)
    producing_command: Mapped[str] = mapped_column(Text)
    scope: Mapped[FactScope] = mapped_column(_enum(FactScope, "fact_scope"))
    scope_ref: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    source_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("session.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    state: Mapped[FactState] = mapped_column(_enum(FactState, "fact_state"), default=FactState.fresh)
    ttl_seconds: Mapped[int] = mapped_column(Integer)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()


class Decision(Base):
    """M5: what the team decided, captured from review, corrections and reverts."""

    __tablename__ = "decision"

    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = _org()
    statement: Mapped[str] = mapped_column(Text)
    origin: Mapped[DecisionOrigin] = mapped_column(_enum(DecisionOrigin, "decision_origin"))
    affected_paths: Mapped[List[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    decided_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    source_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("session.id", ondelete="SET NULL"), nullable=True
    )
    superseded_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decision.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()


class Retrieval(Base):
    """M2: one context request. ``session_id`` is nullable on purpose: an agent this
    system did not start (a future workflow, another vendor) can still ask for context."""

    __tablename__ = "retrieval"

    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = _org()
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("session.id", ondelete="SET NULL"), nullable=True
    )
    requester_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    agent_vendor: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facts_served: Mapped[List[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list, server_default="{}")
    tokens_saved_estimate: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    was_used: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = _created()
