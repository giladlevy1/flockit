from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from flockit_server.models import Origin, Outcome, Role

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email(value: str) -> str:
    value = value.strip().lower()
    if not _EMAIL.match(value) or len(value) > 320:
        raise ValueError("Enter a valid email address")
    return value


def _password(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Use at least 8 characters")
    if len(value) > 256:
        raise ValueError("Too long")
    return value


# --- Ingest (wire format shared with the collector) --------------------------


class IngestSession(BaseModel):
    model_config = ConfigDict(extra="ignore")

    external_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_\-]+$")
    agent_vendor: str = Field(default="claude-code", min_length=1, max_length=64)
    agent_version: Optional[str] = Field(default=None, max_length=64)
    agent_model: Optional[str] = Field(default=None, max_length=120)
    repo: Optional[str] = Field(default=None, max_length=300)
    branch: Optional[str] = Field(default=None, max_length=200)
    task_ref: Optional[str] = Field(default=None, max_length=300)
    origin: Origin = Origin.human
    start_source: Optional[str] = Field(default=None, max_length=32)
    end_reason: Optional[str] = Field(default=None, max_length=64)
    task_id: Optional[uuid.UUID] = None


class TranscriptMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=64)
    seq: int = Field(ge=0, le=10_000_000)
    role: Literal["user", "assistant"]
    kind: Literal["text", "tool_use", "tool_result"]
    tool_name: Optional[str] = Field(default=None, max_length=80)
    content: str = Field(max_length=100_000)
    at: datetime


class TranscriptUsage(BaseModel):
    input: int = Field(default=0, ge=0, le=10**10)
    output: int = Field(default=0, ge=0, le=10**10)
    cache_read: int = Field(default=0, ge=0, le=10**10)
    cache_write: int = Field(default=0, ge=0, le=10**10)


class TranscriptFile(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    edits: int = Field(default=1, ge=0, le=100_000)


class TranscriptIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = Field(default=None, max_length=300)
    messages: List[TranscriptMessage] = Field(default=[], max_length=500)
    usage: TranscriptUsage = TranscriptUsage()
    files: List[TranscriptFile] = Field(default=[], max_length=500)


class IngestEventIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: uuid.UUID
    type: Literal["session.start", "session.activity", "session.update", "session.end", "session.transcript"]
    occurred_at: datetime
    collector_version: Optional[str] = Field(default=None, max_length=32)
    session: IngestSession
    transcript: Optional[TranscriptIn] = None


class IngestBatch(BaseModel):
    events: List[dict] = Field(max_length=500)


class IngestResult(BaseModel):
    accepted: int
    duplicates: int
    rejected: int


# --- People ------------------------------------------------------------------


class TeamRef(BaseModel):
    id: uuid.UUID
    name: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    kind: str = "human"
    dispatch_mode: str = "ask"
    role: Role
    is_active: bool
    teams: List[TeamRef]
    created_at: datetime
    last_login_at: Optional[datetime]
    session_count: int = 0
    last_session_at: Optional[datetime] = None


class UserCreate(BaseModel):
    email: str
    name: str = Field(min_length=1, max_length=200)
    role: Role = Role.developer
    password: str
    team_ids: List[uuid.UUID] = []

    _v_email = field_validator("email")(_email)
    _v_password = field_validator("password")(_password)


class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    role: Optional[Role] = None
    is_active: Optional[bool] = None
    team_ids: Optional[List[uuid.UUID]] = None
    password: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _pw(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _password(v)


class TeamOut(BaseModel):
    id: uuid.UUID
    name: str
    member_ids: List[uuid.UUID]


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    member_ids: Optional[List[uuid.UUID]] = None


# --- Auth --------------------------------------------------------------------


class SetupIn(BaseModel):
    org_name: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    email: str
    password: str

    _v_email = field_validator("email")(_email)
    _v_password = field_validator("password")(_password)


class LoginIn(BaseModel):
    email: str
    password: str = Field(max_length=256)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()


class PasswordChange(BaseModel):
    current_password: str
    new_password: str

    _v_password = field_validator("new_password")(_password)


class OrgOut(BaseModel):
    id: uuid.UUID
    name: str


class MeOut(BaseModel):
    user: UserOut
    org: OrgOut
    scope: Literal["organisation", "team", "self"]
    # What the UI needs to decide between "here is your work" and "here is how to start".
    onboarded: bool = False
    slack_linked: bool = False


# --- Tokens ------------------------------------------------------------------


class TokenOut(BaseModel):
    id: uuid.UUID
    kind: str = "collector"
    name: str
    prefix: str
    created_at: datetime
    last_used_at: Optional[datetime]


class TokenCreated(TokenOut):
    token: str


class TokenIn(BaseModel):
    kind: Literal["collector", "mcp"] = "collector"
    name: str = Field(default="My laptop", min_length=1, max_length=120)


# --- Sessions ----------------------------------------------------------------


class OwnerOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    teams: List[str]


class ActorOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str


class SessionOut(BaseModel):
    id: uuid.UUID
    owner: OwnerOut
    actor: Optional[ActorOut] = None
    title: Optional[str] = None
    task: Optional[dict] = None
    origin: Origin
    agent_vendor: str
    agent_version: Optional[str]
    agent_model: Optional[str]
    models_used: List[str]
    repo: Optional[str]
    branch: Optional[str]
    task_ref: Optional[str]
    started_at: datetime
    last_seen_at: datetime
    ended_at: Optional[datetime]
    duration_seconds: int
    status: Literal["live", "idle", "ended"]
    outcome: Outcome
    end_reason: Optional[str]
    turn_count: int
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_cache_read: int = 0
    tokens_cache_write: int = 0
    tool_calls: int = 0
    message_count: int = 0
    files_touched: int = 0


class SessionPage(BaseModel):
    items: List[SessionOut]
    total: int
    limit: int
    offset: int
