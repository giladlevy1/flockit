"""Database schema.

Identity (organisation, user, team), sessions and their captured transcripts, and
the work layer: tasks (``workflow_run``), workflows, machines that execute tasks
(developer laptops and AI-developer runners) and the audit log. ``fact``,
``decision`` and ``retrieval`` are schema only, for the memory milestones.

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
    Computed,
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
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
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


class UserKind(str, enum.Enum):
    human = "human"
    ai = "ai"  # an AI developer: a member of the org whose sessions run on a runner


class DispatchMode(str, enum.Enum):
    """What a person allows workflows to do on their machine."""

    off = "off"  # never send me tasks
    ask = "ask"  # offer tasks; I accept each one (default)
    auto = "auto"  # workflows set to auto-start may start headless sessions without asking


class Continuity(str, enum.Enum):
    """What happens to a live session when the machine it runs on goes away.

    A closed laptop does not end a Claude Code session: the agent simply stops reporting.
    With ``auto``, Flockit hands that work to the person's own AI developer, which picks it
    up in the cloud with the same conversation and the same working tree.
    """

    off = "off"  # the session just stops, as it always has
    auto = "auto"  # hand it to my AI developer and keep going


class RunMode(str, enum.Enum):
    ask = "ask"  # the assignee accepts before anything runs
    auto = "auto"  # starts headless if the assignee allows auto-start (always, for AI developers)


class PermissionProfile(str, enum.Enum):
    read_only = "read_only"  # plan mode: investigate and report, no edits
    edit = "edit"  # may edit files; shell commands still need permission
    full = "full"  # everything; only honoured inside runner sandboxes


class RunStatus(str, enum.Enum):
    offered = "offered"  # waiting for the assignee to accept
    queued = "queued"  # ready for a machine to pick up
    starting = "starting"  # claimed by a machine, preparing the workspace
    running = "running"  # the agent session is live
    succeeded = "succeeded"
    failed = "failed"
    declined = "declined"
    cancelled = "cancelled"


ACTIVE_RUN_STATUSES = (RunStatus.offered, RunStatus.queued, RunStatus.starting, RunStatus.running)


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
    # The address developers' machines use to reach Flockit. Recorded from the admin's
    # browser at setup (a trusted request) so later requests' Host headers are never trusted.
    public_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = _created()


class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_user_org_email"),
        # One personal AI developer per person, so a handoff never has to choose.
        Index("uq_user_personal_for", "personal_for_id", unique=True, postgresql_where=text("personal_for_id IS NOT NULL")),
    )

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
    kind: Mapped[UserKind] = mapped_column(_enum(UserKind, "user_kind"), default=UserKind.human, server_default="human")
    dispatch_mode: Mapped[DispatchMode] = mapped_column(
        _enum(DispatchMode, "dispatch_mode"), default=DispatchMode.ask, server_default="ask"
    )
    # AI developers only
    agent_vendor: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    agent_model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    runner_pool: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sponsor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The workbench this AI developer works in: its database and services, kept between tasks.
    environment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("environment.id", ondelete="SET NULL"), nullable=True
    )
    # Where this AI developer works unless a task says otherwise.
    default_repo: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    # People only: linked by typing a code into Slack, so Flockit never calls Slack to look anyone up.
    # The code is stored as a hash and expires; it is not an API token and grants nothing on its own.
    slack_user_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    slack_link_code_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    slack_link_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set the first time someone finishes (or skips) the getting-started steps.
    onboarded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # People: what happens to a live session when this person's machine goes away.
    continuity: Mapped[Continuity] = mapped_column(
        _enum(Continuity, "continuity_mode"), default=Continuity.off, server_default="off"
    )
    # AI developers: the one person this agent belongs to. A personal AI developer only ever
    # continues its owner's work, so the handoff needs no decision about who it goes to.
    personal_for_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )

    teams: Mapped[List["Team"]] = relationship(secondary="team_member", back_populates="members", lazy="selectin")


class Environment(Base):
    """A workbench for an AI developer: the services it develops against — a database with
    realistic data, a queue, a stand-in for one customer's account — kept between tasks the
    way a person's own machine is. An agent that can run the app and the tests against
    something close to production can check its own work before a human ever sees it.

    ``services`` is a list of ``{name, image, env, port, url_env, url, ready}``. The runner
    starts each one on a private network next to the sandbox, keeps its volume, and injects
    ``url_env=url`` (for example ``DATABASE_URL``) into the agent's environment. Nothing here
    is a secret: values the org would not paste into a ticket belong in ``secret_names``,
    which are passed through from the runner's own environment by name.
    """

    __tablename__ = "environment"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_environment_org_name"),)

    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = _org()
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    services: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    variables: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    secret_names: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    # Runs once, the first time the services are created: migrations, seed data, a customer fixture.
    setup_script: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Keep the services and their data between tasks (a real workbench) or throw them away each time.
    persistent: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


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
    # "collector" writes sessions and nothing else; "mcp" reads this person's own view of
    # Flockit from their editor. Separate kinds so a token stolen from a laptop's config
    # cannot be used to read the organisation's transcripts.
    kind: Mapped[str] = mapped_column(String(16), default="collector", server_default="collector")
    prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _created()
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Ephemeral tokens minted for one AI-developer task expire and are scoped to it.
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_run.id", ondelete="CASCADE"), nullable=True
    )


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
    # Who did the work: the owner themselves, or an AI developer the owner sponsors.
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, index=True
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
    title: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)  # the first prompt, redacted
    tokens_input: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    tokens_output: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    tokens_cache_read: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    tokens_cache_write: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    tool_calls: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    files_touched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    collector_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # A snapshot of the working tree, taken on the developer's machine while they work, so a
    # session can be continued elsewhere without them having to commit anything first.
    wip_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    wip_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    wip_pushed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    wip_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when this session was handed to an AI developer because the machine went away.
    continued_by_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_run.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    owner: Mapped[User] = relationship(lazy="joined", innerjoin=True, foreign_keys=[human_owner_id])
    actor: Mapped[Optional[User]] = relationship(lazy="joined", foreign_keys=[actor_id])


class SessionMessage(Base):
    """One transcript entry: a prompt, a reply, a tool call or a tool result. Redacted on
    the developer's machine before it was sent. ``search`` is a generated full-text index."""

    __tablename__ = "session_message"
    __table_args__ = (
        UniqueConstraint("session_id", "entry_id", name="uq_session_message_entry"),
        Index("ix_session_message_search", "search", postgresql_using="gin"),
        Index("ix_session_message_session_seq", "session_id", "seq"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("session.id", ondelete="CASCADE"))
    entry_id: Mapped[str] = mapped_column(String(64))
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    kind: Mapped[str] = mapped_column(String(16))  # text | tool_use | tool_result
    tool_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    search: Mapped[Optional[str]] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', coalesce(content, ''))", persisted=True), nullable=True
    )


class SessionFile(Base):
    """A file an agent edited or created, relative to the repository root."""

    __tablename__ = "session_file"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("session.id", ondelete="CASCADE"), primary_key=True
    )
    path: Mapped[str] = mapped_column(String(500), primary_key=True)
    edits: Mapped[int] = mapped_column(Integer, default=0)


class IngestEvent(Base):
    """Seen event ids, so collector retries are idempotent."""

    __tablename__ = "ingest_event"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("session.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    received_at: Mapped[datetime] = _created()


# --- Work: tasks, workflows, machines ------------------------------------------


class Workflow(Base):
    """A reusable definition: what to ask the agent, where, for whom, and when."""

    __tablename__ = "workflow"

    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = _org()
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prompt_template: Mapped[str] = mapped_column(Text)
    repo: Mapped[str] = mapped_column(String(300))
    base_branch: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    assignee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"))
    mode: Mapped[RunMode] = mapped_column(_enum(RunMode, "run_mode"), default=RunMode.ask)
    permission_profile: Mapped[PermissionProfile] = mapped_column(
        _enum(PermissionProfile, "permission_profile"), default=PermissionProfile.edit
    )
    schedule_cron: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    schedule_timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    webhook_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    webhook_secret_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    webhook_filter: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    assignee: Mapped[User] = relationship(lazy="joined", foreign_keys=[assignee_id])


class WorkflowRun(Base):
    """A task: one unit of work for one assignee, from a workflow or assigned directly."""

    __tablename__ = "workflow_run"
    __table_args__ = (
        Index("ix_run_org_created", "org_id", "created_at"),
        Index("ix_run_assignee_status", "assignee_id", "status"),
    )

    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = _org()
    workflow_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(300), default="Task", server_default="Task")
    prompt: Mapped[str] = mapped_column(Text, default="", server_default="")
    repo: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    base_branch: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    branch: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    task_ref: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="RESTRICT"), nullable=True
    )
    mode: Mapped[RunMode] = mapped_column(_enum(RunMode, "run_mode"), default=RunMode.ask, server_default="ask")
    permission_profile: Mapped[PermissionProfile] = mapped_column(
        _enum(PermissionProfile, "permission_profile"), default=PermissionProfile.edit, server_default="edit"
    )
    status: Mapped[RunStatus] = mapped_column(
        _enum(RunStatus, "run_status"), default=RunStatus.queued, server_default="queued"
    )
    trigger: Mapped[str] = mapped_column(String(32), default="manual", server_default="manual")
    trigger_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    triggered_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    machine_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("machine.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("session.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    interactive: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Where to report the result: ``{"slack": {"channel": "C…", "thread_ts": "…"}}``. The runner
    # posts it, because the server makes no outbound calls.
    notify: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pr_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    assignee: Mapped[Optional[User]] = relationship(lazy="joined", foreign_keys=[assignee_id])
    triggered_by: Mapped[Optional[User]] = relationship(lazy="joined", foreign_keys=[triggered_by_id])
    workflow: Mapped[Optional[Workflow]] = relationship(lazy="joined", foreign_keys=[workflow_id])
    machine: Mapped[Optional["Machine"]] = relationship(lazy="joined", foreign_keys=[machine_id])


class Machine(Base):
    """Something that executes tasks: a developer's laptop agent or an AI-developer runner."""

    __tablename__ = "machine"

    id: Mapped[uuid.UUID] = _pk()
    org_id: Mapped[uuid.UUID] = _org()
    kind: Mapped[str] = mapped_column(String(16))  # laptop | runner
    name: Mapped[str] = mapped_column(String(200))
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=True, index=True
    )
    pool: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    token_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    token_prefix: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    platform: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    capabilities: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    capacity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    """Who did what: dispatching work to people and agents must be traceable."""

    __tablename__ = "audit_event"
    __table_args__ = (Index("ix_audit_org_created", "org_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = _org()
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    detail: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _created()


# --- Schema only: the memory milestones ---------------------------------------


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
