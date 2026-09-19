"""Workbenches: the services an AI developer develops against.

A person's machine has a database with realistic data, a queue, maybe a copy of one
customer's account. An agent with the same thing can run the app, run the tests and
check its own work before a human reads a line of it. That is the difference between
a patch that compiles and a change someone can ship.

Flockit stores the *declaration* (which images, which ports, which variable names) and
the runner builds it next to the sandbox. Secrets are named here, never stored: the
runner passes them through from its own environment.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server import runs
from flockit_server.db import get_db
from flockit_server.deps import current_user, require_admin
from flockit_server.models import Environment, User, UserKind

router = APIRouter(tags=["environments"])

MAX_SERVICES = 4
NAME = re.compile(r"^[a-z][a-z0-9\-]{0,30}$")
# A registry reference: repo, optional registry host, optional tag or digest. No flags, no spaces.
IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,150}(?::[A-Za-z0-9._\-]{1,80})?(?:@sha256:[a-f0-9]{64})?$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,60}$")


class Service(BaseModel):
    """One container that runs beside the agent for the life of the workbench."""

    name: str = Field(max_length=31)
    image: str = Field(max_length=200)
    env: Dict[str, str] = Field(default_factory=dict)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    # The variable the agent reads to reach this service, and what to put in it.
    url_env: Optional[str] = Field(default=None, max_length=61)
    url: Optional[str] = Field(default=None, max_length=300)
    # Shell command run inside the service until it succeeds, so the agent never
    # starts against a database that is still booting.
    ready: Optional[str] = Field(default=None, max_length=200)
    # Data the service keeps between tasks (a named volume), e.g. /var/lib/postgresql/data.
    data_path: Optional[str] = Field(default=None, max_length=200)


class EnvironmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=8_000)
    services: List[Service] = Field(default_factory=list)
    variables: Dict[str, str] = Field(default_factory=dict)
    secret_names: List[str] = Field(default_factory=list)
    setup_script: Optional[str] = Field(default=None, max_length=20_000)
    persistent: bool = True


class EnvironmentOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    services: List[dict]
    variables: Dict[str, str]
    secret_names: List[str]
    setup_script: Optional[str]
    persistent: bool
    created_at: datetime
    updated_at: datetime
    used_by: List[dict]


def _no_control(value: str, what: str) -> str:
    if any(c in value for c in "\r\n\x00"):
        raise HTTPException(422, f"{what} cannot contain line breaks")
    return value


def validate(body: EnvironmentIn) -> None:
    """Everything here ends up on a runner's docker command line, so it is checked here
    rather than trusted there (the runner checks again)."""
    if not NAME.match(body.name.strip()):
        raise HTTPException(422, "The name may use lower-case letters, digits and dashes")
    if len(body.services) > MAX_SERVICES:
        raise HTTPException(422, f"At most {MAX_SERVICES} services per workbench")
    seen = set()
    for s in body.services:
        if not NAME.match(s.name):
            raise HTTPException(422, f"Service name {s.name!r}: lower-case letters, digits and dashes")
        if s.name in seen:
            raise HTTPException(422, f"Two services are called {s.name!r}")
        seen.add(s.name)
        if not IMAGE.match(s.image):
            raise HTTPException(422, f"{s.image!r} is not an image name (registry/name:tag)")
        for key, value in s.env.items():
            if not ENV_NAME.match(key):
                raise HTTPException(422, f"{key!r} is not a variable name (A-Z, digits, underscore)")
            _no_control(value, f"{key}")
            if len(value) > 500:
                raise HTTPException(422, f"{key} is too long")
        if s.url_env and not ENV_NAME.match(s.url_env):
            raise HTTPException(422, f"{s.url_env!r} is not a variable name")
        if s.url:
            _no_control(s.url, "The service URL")
        if s.ready:
            _no_control(s.ready, "The readiness command")
        if s.data_path and (not s.data_path.startswith("/") or ".." in s.data_path):
            raise HTTPException(422, "The data path must be absolute")
    for key, value in body.variables.items():
        if not ENV_NAME.match(key):
            raise HTTPException(422, f"{key!r} is not a variable name (A-Z, digits, underscore)")
        _no_control(value, key)
    for name in body.secret_names:
        if not ENV_NAME.match(name):
            raise HTTPException(422, f"{name!r} is not a variable name")


async def out(db: AsyncSession, env: Environment) -> EnvironmentOut:
    used = (
        await db.execute(
            select(User.id, User.name).where(User.environment_id == env.id, User.kind == UserKind.ai).order_by(User.name)
        )
    ).all()
    return EnvironmentOut(
        id=env.id,
        name=env.name,
        description=env.description,
        services=list(env.services or []),
        variables=dict(env.variables or {}),
        secret_names=list(env.secret_names or []),
        setup_script=env.setup_script,
        persistent=env.persistent,
        created_at=env.created_at,
        updated_at=env.updated_at,
        used_by=[{"id": i, "name": n} for i, n in used],
    )


def spec(env: Optional[Environment]) -> Optional[Dict[str, Any]]:
    """What a runner needs to build the workbench. Used by the runner poll endpoint."""
    if env is None:
        return None
    return {
        "id": str(env.id),
        "name": env.name,
        "services": list(env.services or []),
        "variables": dict(env.variables or {}),
        "secret_names": list(env.secret_names or []),
        "setup_script": env.setup_script,
        "persistent": env.persistent,
    }


async def _check_name_free(
    db: AsyncSession, org_id: uuid.UUID, name: str, except_id: Optional[uuid.UUID] = None
) -> None:
    """Names are unique per organisation. Checked here so a clash is a 409 with a sentence
    in it, rather than a unique-constraint violation surfacing as a 500."""
    q = select(func.count()).select_from(Environment).where(
        Environment.org_id == org_id, Environment.name == name.strip()
    )
    if except_id is not None:
        q = q.where(Environment.id != except_id)
    if (await db.execute(q)).scalar_one():
        raise HTTPException(409, f"A workbench called {name} already exists")


async def _get(db: AsyncSession, org_id: uuid.UUID, env_id: uuid.UUID) -> Environment:
    env = (
        await db.execute(select(Environment).where(Environment.id == env_id, Environment.org_id == org_id))
    ).scalar_one_or_none()
    if env is None:
        raise HTTPException(404, "Workbench not found")
    return env


@router.get("/api/environments", response_model=List[EnvironmentOut])
async def list_environments(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(Environment).where(Environment.org_id == user.org_id).order_by(Environment.name))
    ).scalars().all()
    return [await out(db, e) for e in rows]


@router.post("/api/environments", response_model=EnvironmentOut, status_code=201)
async def create_environment(body: EnvironmentIn, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    validate(body)
    await _check_name_free(db, admin.org_id, body.name)
    env = Environment(org_id=admin.org_id)
    _apply(env, body)
    db.add(env)
    await db.flush()
    await runs.audit(db, admin.org_id, admin, "environment.created", "environment", env.id, {"name": env.name})
    await db.commit()
    await db.refresh(env)
    return await out(db, env)


def _apply(env: Environment, body: EnvironmentIn) -> None:
    env.name = body.name.strip()
    env.description = body.description.strip()
    env.services = [s.model_dump() for s in body.services]
    env.variables = dict(body.variables)
    env.secret_names = list(body.secret_names)
    env.setup_script = (body.setup_script or "").strip() or None
    env.persistent = body.persistent


@router.put("/api/environments/{env_id}", response_model=EnvironmentOut)
async def update_environment(
    env_id: uuid.UUID, body: EnvironmentIn, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    validate(body)
    env = await _get(db, admin.org_id, env_id)
    await _check_name_free(db, admin.org_id, body.name, except_id=env_id)
    _apply(env, body)
    await runs.audit(db, admin.org_id, admin, "environment.updated", "environment", env.id, {"name": env.name})
    await db.commit()
    await db.refresh(env)
    return await out(db, env)


@router.delete("/api/environments/{env_id}", status_code=204)
async def delete_environment(env_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    env = await _get(db, admin.org_id, env_id)
    in_use = (
        await db.execute(select(func.count()).select_from(User).where(User.environment_id == env.id))
    ).scalar_one()
    if in_use:
        raise HTTPException(409, "This workbench is still assigned to an AI developer")
    await runs.audit(db, admin.org_id, admin, "environment.deleted", "environment", env.id, {"name": env.name})
    await db.delete(env)
    await db.commit()


# --- Starting points -------------------------------------------------------------
# Offered in the UI so the first workbench is one click, not a form.

PRESETS: List[dict] = [
    {
        "key": "postgres",
        "title": "Web service with Postgres",
        "description": "A Postgres 16 database the agent can migrate, seed and query while it works. "
        "Its data survives between tasks, so the schema it built yesterday is still there today.",
        "environment": {
            "name": "app-postgres",
            "description": "Postgres 16 on the workbench network as `db`. The agent reads DATABASE_URL.",
            "services": [
                {
                    "name": "db",
                    "image": "postgres:16-alpine",
                    "env": {"POSTGRES_PASSWORD": "flockit", "POSTGRES_USER": "app", "POSTGRES_DB": "app"},
                    "port": 5432,
                    "url_env": "DATABASE_URL",
                    "url": "postgresql://app:flockit@db:5432/app",
                    "ready": "pg_isready -U app",
                    "data_path": "/var/lib/postgresql/data",
                }
            ],
            "variables": {},
            "secret_names": [],
            "setup_script": "# Runs once, when the workbench is first built.\n"
            "# Point it at your schema, for example:\n"
            "#   psql \"$DATABASE_URL\" -f db/schema.sql && psql \"$DATABASE_URL\" -f db/seed.sql\n",
            "persistent": True,
        },
    },
    {
        "key": "postgres-redis",
        "title": "Postgres and Redis",
        "description": "Adds a cache and queue, so background jobs and rate limits behave the way they do in production.",
        "environment": {
            "name": "app-full",
            "description": "Postgres 16 as `db` and Redis 7 as `cache`. The agent reads DATABASE_URL and REDIS_URL.",
            "services": [
                {
                    "name": "db",
                    "image": "postgres:16-alpine",
                    "env": {"POSTGRES_PASSWORD": "flockit", "POSTGRES_USER": "app", "POSTGRES_DB": "app"},
                    "port": 5432,
                    "url_env": "DATABASE_URL",
                    "url": "postgresql://app:flockit@db:5432/app",
                    "ready": "pg_isready -U app",
                    "data_path": "/var/lib/postgresql/data",
                },
                {
                    "name": "cache",
                    "image": "redis:7-alpine",
                    "env": {},
                    "port": 6379,
                    "url_env": "REDIS_URL",
                    "url": "redis://cache:6379/0",
                    "ready": "redis-cli ping",
                    "data_path": "/data",
                },
            ],
            "variables": {},
            "secret_names": [],
            "setup_script": None,
            "persistent": True,
        },
    },
    {
        "key": "customer",
        "title": "One customer's account",
        "description": "A workbench that holds a single customer's shape of data. Give the AI developer that owns this "
        "account the tickets from it: it reproduces the bug against their data instead of a clean fixture.",
        "environment": {
            "name": "customer-acme",
            "description": "Stand-in for Acme Corp: their plan, their volumes, their edge cases. "
            "Anonymised — never a copy of production data.",
            "services": [
                {
                    "name": "db",
                    "image": "postgres:16-alpine",
                    "env": {"POSTGRES_PASSWORD": "flockit", "POSTGRES_USER": "app", "POSTGRES_DB": "acme"},
                    "port": 5432,
                    "url_env": "DATABASE_URL",
                    "url": "postgresql://app:flockit@db:5432/acme",
                    "ready": "pg_isready -U app",
                    "data_path": "/var/lib/postgresql/data",
                }
            ],
            "variables": {"CUSTOMER": "acme", "PLAN": "enterprise"},
            "secret_names": [],
            "setup_script": "# Load the anonymised fixture for this account:\n"
            "#   psql \"$DATABASE_URL\" -f fixtures/acme.sql\n",
            "persistent": True,
        },
    },
    {
        "key": "none",
        "title": "No services",
        "description": "Just variables. For repositories whose tests run without anything else.",
        "environment": {
            "name": "plain",
            "description": "No services; the agent gets the variables below and nothing more.",
            "services": [],
            "variables": {},
            "secret_names": [],
            "setup_script": None,
            "persistent": False,
        },
    },
]


@router.get("/api/environment-presets")
async def presets(_: User = Depends(current_user)) -> dict:
    return {"items": PRESETS}
