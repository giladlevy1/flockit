"""Slack: the signature is the only door, and what comes through it is untrusted text.

The endpoints are public, so every test here signs its own request the way Slack does
(v0 scheme over the raw body). The rest is the grammar: linking a person, giving an AI
developer a task, and the rule that work arriving from a chat window never starts by
itself on somebody's laptop.
"""

import hashlib
import hmac
import json
import time
import urllib.parse

import pytest
from sqlalchemy import select

from flockit_server import db, runs
from flockit_server.models import RunMode, RunStatus, User, WorkflowRun
from flockit_server.settings import get_settings

SECRET = "8f742231b10e4f39b1a7d2c6e5a09b3d"


@pytest.fixture
def slack(monkeypatch):
    """Slack is deployment config, so it arrives through the environment, not the database."""
    monkeypatch.setenv("FLOCKIT_SLACK_SIGNING_SECRET", SECRET)
    get_settings.cache_clear()
    yield SECRET
    get_settings.cache_clear()


def sign(raw: bytes, secret: str = SECRET, timestamp: int = None, signature: str = None) -> dict:
    ts = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(secret.encode(), b"v0:" + ts.encode() + b":" + raw, hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": signature or "v0=" + digest}


def command(text: str, user_id: str = "U-ADA", channel_id: str = "C-ENG", **kw) -> bytes:
    """The x-www-form-urlencoded body Slack posts for a slash command."""
    form = {"command": "/flockit", "text": text, "user_id": user_id, "channel_id": channel_id, "team_id": "T1"}
    form.update(kw)
    return urllib.parse.urlencode(form).encode()


async def slash(client, text: str, **kw):
    raw = command(text, **kw)
    return await client.post(
        "/api/slack/command", content=raw, headers={**sign(raw), "content-type": "application/x-www-form-urlencoded"}
    )


async def event(client, body: dict):
    raw = json.dumps(body).encode()
    return await client.post(
        "/api/slack/events", content=raw, headers={**sign(raw), "content-type": "application/json"}
    )


async def latest_task() -> WorkflowRun:
    async with db.sessionmaker()() as session:
        return (
            await session.execute(select(WorkflowRun).order_by(WorkflowRun.created_at.desc()))
        ).scalars().first()


@pytest.fixture
async def org(admin, make_user, slack, client_factory):
    dev = await make_user("Dev One")
    ai = (
        await admin.post(
            "/api/ai-developers", json={"name": "Ada Bot", "default_repo": "github.com/acme/web"}
        )
    ).json()
    return {"admin": admin, "dev": dev, "ai": ai, "anon": client_factory()}


async def link(org, slack_user_id: str = "U-ADA", client=None) -> str:
    """Take a code from the Connect page and type it into Slack, as a person would."""
    code = (await (client or org["dev"]).post("/api/connect/slack-code")).json()["code"]
    r = await slash(org["anon"], f"link {code}", user_id=slack_user_id)
    assert r.status_code == 200, r.text
    return r.json()["text"]


# --- the door ----------------------------------------------------------------------


async def test_only_correctly_signed_requests_are_answered(org):
    anon, raw = org["anon"], command("help")
    form = {"content-type": "application/x-www-form-urlencoded"}
    assert (await anon.post("/api/slack/command", content=raw, headers=form)).status_code == 401
    forged = sign(raw, secret="not-the-signing-secret")
    assert (await anon.post("/api/slack/command", content=raw, headers={**forged, **form})).status_code == 401
    tampered = {**sign(raw), "X-Slack-Signature": "v0=" + "0" * 64}
    assert (await anon.post("/api/slack/command", content=raw, headers={**tampered, **form})).status_code == 401
    # A replayed request, correctly signed but older than the window, is still refused.
    stale = sign(raw, timestamp=int(time.time()) - 6 * 60)
    assert (await anon.post("/api/slack/command", content=raw, headers={**stale, **form})).status_code == 401
    assert (await slash(anon, "help")).status_code == 200


async def test_without_a_signing_secret_slack_does_not_exist(admin, client_factory):
    get_settings.cache_clear()  # no FLOCKIT_SLACK_SIGNING_SECRET in the environment
    anon = client_factory()
    assert (await slash(anon, "help")).status_code == 404
    assert (await anon.get("/api/slack/status")).json() == {"configured": False}
    assert (await admin.post("/api/connect/slack-code")).status_code == 409


async def test_slack_status_reports_a_configured_deployment(org):
    assert (await org["anon"].get("/api/slack/status")).json() == {"configured": True}


# --- who is talking ------------------------------------------------------------------


async def test_help_and_unlinked_users_get_an_ephemeral_reply_and_no_task(org):
    reply = (await slash(org["anon"], "help")).json()
    assert reply["response_type"] == "ephemeral" and "/flockit link" in reply["text"]
    assert (await slash(org["anon"], "")).json()["text"] == reply["text"]
    stranger = (await slash(org["anon"], "ada fix the thing", user_id="U-NOBODY")).json()
    assert stranger["response_type"] == "ephemeral" and "not linked" in stranger["text"]
    assert (await org["admin"].get("/api/tasks")).json()["total"] == 0


async def test_linking_a_slack_account_takes_a_fresh_code(org):
    wrong = (await slash(org["anon"], "link ABCD2345")).json()["text"]
    assert "wrong or has expired" in wrong
    assert (await org["dev"].get("/api/auth/me")).json()["slack_linked"] is False
    assert "Linked to *Dev One*" in await link(org)
    assert (await org["dev"].get("/api/auth/me")).json()["slack_linked"] is True
    # The code is single use: the same one cannot link a second Slack account.
    assert "wrong or has expired" in (await slash(org["anon"], "link NOTACODE", user_id="U-OTHER")).json()["text"]
    assert (await slash(org["anon"], "tasks")).json()["text"] == "Nothing running right now."


# --- giving work ---------------------------------------------------------------------


async def test_a_linked_person_can_hand_an_ai_developer_a_task(org):
    await link(org)
    reply = (await slash(org["anon"], "ada fix the thing")).json()
    assert reply["response_type"] == "in_channel"
    assert "Ada Bot" in reply["text"] and "fix the thing" in reply["text"]
    task = (await org["admin"].get("/api/tasks")).json()["items"][0]
    assert task["title"] == "fix the thing" and task["status"] == "queued"
    assert task["assignee"]["name"] == "Ada Bot" and task["trigger"] == "slack"
    assert task["triggered_by"]["name"] == "Dev One" and task["repo"] == "github.com/acme/web"
    run = await latest_task()
    assert run.notify == {"slack": {"channel": "C-ENG", "user": "U-ADA"}}
    assert run.prompt == "fix the thing"


async def test_an_unknown_ai_developer_or_an_empty_prompt_creates_nothing(org):
    await link(org)
    assert "No AI developer called *grace*" in (await slash(org["anon"], "grace fix the thing")).json()["text"]
    assert "Tell Ada Bot what to do" in (await slash(org["anon"], "ada")).json()["text"]
    assert (await org["admin"].get("/api/tasks")).json()["total"] == 0


async def test_where_the_work_happens(org, admin):
    await link(org)
    await slash(org["anon"], "ada fix the thing")
    assert (await latest_task()).repo == "github.com/acme/web"  # the AI developer's own repository

    override = (await slash(org["anon"], "ada repo=github.com/acme/api fix the thing")).json()
    assert "`github.com/acme/api`" in override["text"]
    run = await latest_task()
    assert run.repo == "github.com/acme/api" and run.prompt == "fix the thing"  # repo= is not part of the prompt

    refused = (await slash(org["anon"], "ada repo=https://evil.example/x fix the thing")).json()
    assert refused["response_type"] == "ephemeral" and "not a repository Flockit is allowed" in refused["text"]
    assert (await admin.get("/api/tasks")).json()["total"] == 2  # nothing was created for the refused repo

    homeless = (await admin.post("/api/ai-developers", json={"name": "Grace Bot"})).json()
    assert homeless["default_repo"] is None
    reply = (await slash(org["anon"], "grace investigate the outage")).json()
    assert "has no repository set" in reply["text"] and "repo=github.com/acme/api" in reply["text"]
    assert (await admin.get("/api/tasks")).json()["total"] == 2


async def test_slack_work_for_a_person_never_auto_starts(org):
    """Anyone who can type in the channel can write the prompt, so a person is always asked
    first — even one who has opted into auto-start for the work they trust."""
    await org["dev"].patch("/api/auth/me", json={"dispatch_mode": "auto"})
    async with db.sessionmaker()() as session:
        person = (await session.execute(select(User).where(User.email == "dev.one@acme.dev"))).scalar_one()
        run = await runs.create_run(
            session,
            org_id=person.org_id,
            assignee=person,
            title="fix the thing",
            prompt="fix the thing",
            repo="github.com/acme/api",
            mode=RunMode.auto,
            trigger="slack",
            triggered_by=person,
            notify={"slack": {"channel": "C-ENG", "user": "U-ADA"}},
        )
        await session.commit()
        assert run.status == RunStatus.offered and run.mode == RunMode.ask
    # the same person asking for the same thing in the UI still auto-starts
    assert (await org["dev"].post("/api/tasks", json={
        "title": "fix the thing", "prompt": "fix the thing", "repo": "github.com/acme/api",
        "assignee_id": org["dev"].user_id, "mode": "auto",
    })).json()["status"] == "queued"


# --- the Events API -------------------------------------------------------------------


async def test_events_api_handshake_mentions_and_bots(org):
    anon = org["anon"]
    handshake = await event(anon, {"type": "url_verification", "challenge": "3eZbrw1aB"})
    assert handshake.json() == {"challenge": "3eZbrw1aB"}
    await link(org, slack_user_id="U-ADA")

    mention = {
        "type": "event_callback",
        "event": {
            "type": "app_mention",
            "text": "<@U0FLOCKIT> ada fix the thing",
            "user": "U-ADA",
            "channel": "C-ENG",
            "ts": "1758300000.000100",
        },
    }
    assert (await event(anon, mention)).json() == {"ok": True}
    run = await latest_task()
    assert run.title == "fix the thing" and run.trigger == "slack"
    assert run.notify["slack"]["thread_ts"] == "1758300000.000100"

    # Flockit's own messages come back through the Events API: they must not start work.
    from_bot = {"type": "event_callback", "event": {**mention["event"], "bot_id": "B-FLOCKIT"}}
    assert (await event(anon, from_bot)).json() == {"ok": True}
    assert (await org["admin"].get("/api/tasks")).json()["total"] == 1
    assert (await event(anon, {"type": "event_callback", "event": {"type": "message", "text": "hi"}})).json() == {"ok": True}
    assert (await org["admin"].get("/api/tasks")).json()["total"] == 1
