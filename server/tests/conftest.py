"""Tests run against a real Postgres. Point FLOCKIT_TEST_DATABASE_URL at a disposable database."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

TEST_URL = os.environ.get(
    "FLOCKIT_TEST_DATABASE_URL", "postgresql+asyncpg://flockit:flockit@localhost:55432/flockit_test"
)
os.environ["FLOCKIT_DATABASE_URL"] = TEST_URL

from flockit_server import db  # noqa: E402
from flockit_server.cli import alembic_config  # noqa: E402
from flockit_server.main import create_app  # noqa: E402
from flockit_server.settings import get_settings  # noqa: E402

TABLES = [
    "ingest_event", "retrieval", "decision", "fact", "session", "workflow_run", "api_token",
    "login_session", "team_member", "team", '"user"', "organization",
]


@pytest.fixture(scope="session", autouse=True)
async def database():
    admin_url = TEST_URL.rsplit("/", 1)[0] + "/postgres"
    name = TEST_URL.rsplit("/", 1)[1]
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await engine.dispose()

    import asyncio

    from alembic import command

    await asyncio.to_thread(command.upgrade, alembic_config(TEST_URL), "head")
    yield
    await db.dispose()


@pytest.fixture(autouse=True)
async def clean():
    async with db.engine().begin() as conn:
        await conn.execute(text("TRUNCATE " + ", ".join(TABLES) + " CASCADE"))
    yield


@pytest.fixture
def app():
    get_settings.cache_clear()
    return create_app(run_sweeper=False)


class Client(httpx.AsyncClient):
    """A browser-like client: keeps its login cookie and sends the CSRF header."""

    async def request(self, method, url, **kwargs):  # type: ignore[override]
        headers = kwargs.pop("headers", None) or {}
        headers.setdefault("X-Flockit-Request", "1")
        return await super().request(method, url, headers=headers, **kwargs)


@pytest.fixture
def client_factory(app):
    clients = []

    def make() -> Client:
        c = Client(transport=httpx.ASGITransport(app=app), base_url="http://flockit.test")
        clients.append(c)
        return c

    yield make


@pytest.fixture
async def admin(client_factory):
    c = client_factory()
    r = await c.post(
        "/api/setup", json={"org_name": "Acme", "name": "Ada Admin", "email": "ada@acme.dev", "password": "password-1"}
    )
    assert r.status_code == 201, r.text
    return c


@pytest.fixture
def make_user(admin, client_factory):
    async def make(name: str, role: str = "developer", team_ids=()):
        email = name.lower().replace(" ", ".") + "@acme.dev"
        r = await admin.post(
            "/api/users",
            json={"email": email, "name": name, "role": role, "password": "password-1", "team_ids": list(team_ids)},
        )
        assert r.status_code == 201, r.text
        c = client_factory()
        r = await c.post("/api/auth/login", json={"email": email, "password": "password-1"})
        assert r.status_code == 200, r.text
        c.user = r  # noqa
        c.user_id = (await c.get("/api/auth/me")).json()["user"]["id"]
        return c

    return make


async def collector_token(client) -> str:
    r = await client.post("/api/tokens", json={"name": "laptop"})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def event(kind: str, session_id: str, at: datetime | None = None, **fields) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "type": kind,
        "occurred_at": (at or datetime.now(timezone.utc)).isoformat(),
        "collector_version": "0.1.0",
        "session": {"external_id": session_id, "agent_vendor": "claude-code", **fields},
    }


async def send(client, token: str, *events: dict) -> httpx.Response:
    return await client.post(
        "/api/ingest/events", json={"events": list(events)}, headers={"Authorization": "Bearer " + token}
    )


def ago(**kw) -> datetime:
    return datetime.now(timezone.utc) - timedelta(**kw)
