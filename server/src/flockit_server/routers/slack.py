"""Slack: start work from where the conversation already happens.

    /flockit ada the checkout webhook retries forever on 429, have a look
    @flockit ada ^ this one too

Everything here is **inbound**. Flockit never calls Slack: the slash command is answered
in the reply to Slack's own request, and the result is posted later by the runner that did
the work (it already has network access and holds the bot token). That keeps the promise
that the server makes no outbound calls.

People are linked to their Slack account by typing a short code from the Connect page,
so Flockit never has to ask Slack who anyone is.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import urllib.parse
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server import runs
from flockit_server.db import get_db
from flockit_server.models import ACTIVE_RUN_STATUSES, RunMode, RunStatus, User, UserKind, WorkflowRun
from flockit_server.security import hash_token
from flockit_server.settings import get_settings

router = APIRouter(prefix="/api/slack", tags=["slack"])

MAX_BODY = 128 * 1024
SIGNATURE_WINDOW = 60 * 5
HELP = (
    "*Flockit*\n"
    "• `/flockit <ai developer> <what to do>` — give an AI developer a task\n"
    "• `/flockit <ai developer> repo=github.com/acme/api <what to do>` — work somewhere other than its usual repository\n"
    "• `/flockit tasks` — what your AI developers are working on\n"
    "• `/flockit link <code>` — connect this Slack account (get the code from Flockit → Connect)"
)


def _ephemeral(text: str) -> dict:
    return {"response_type": "ephemeral", "text": text}


async def _read(request: Request) -> bytes:
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY:
            raise HTTPException(413, "That message is too large")
    return body


def verify(raw: bytes, request: Request) -> None:
    """Slack signs every request with the app's signing secret. Anything unsigned, stale
    or mismatched is refused: this endpoint is public, so the signature is the only door."""
    secret = get_settings().slack_signing_secret
    if not secret:
        raise HTTPException(404, "Slack is not configured on this Flockit")
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if not timestamp.lstrip("-").isdigit() or abs(time.time() - int(timestamp)) > SIGNATURE_WINDOW:
        raise HTTPException(401, "Stale request")
    expected = "v0=" + hmac.new(secret.encode(), b"v0:" + timestamp.encode() + b":" + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Bad signature")


def _form(raw: bytes) -> Dict[str, str]:
    return {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True).items()}


async def _person(db: AsyncSession, slack_user_id: str) -> Optional[User]:
    if not slack_user_id:
        return None
    return (
        await db.execute(
            select(User).where(
                User.slack_user_id == slack_user_id, User.kind == UserKind.human, User.is_active.is_(True)
            )
        )
    ).scalars().first()


async def _link(db: AsyncSession, slack_user_id: str, code: str) -> str:
    code = re.sub(r"[^A-Za-z0-9]", "", code).upper()
    if len(code) < 6:
        return "That does not look like a link code. Open Flockit → Connect to get one."
    user = (
        await db.execute(select(User).where(User.slack_link_code_hash == hash_token(code), User.kind == UserKind.human))
    ).scalars().first()
    if user is None or not user.slack_link_expires_at or user.slack_link_expires_at < runs.now():
        return "That code is wrong or has expired. Open Flockit → Connect for a new one."
    # One Slack account per person: clear the code and take the id.
    already = (
        await db.execute(select(User).where(User.slack_user_id == slack_user_id, User.id != user.id))
    ).scalars().all()
    for other in already:
        other.slack_user_id = None
    user.slack_user_id = slack_user_id
    user.slack_link_code_hash = None
    user.slack_link_expires_at = None
    await runs.audit(db, user.org_id, user, "slack.linked", "user", user.id, {"slack_user_id": slack_user_id})
    await db.commit()
    return f"Linked to *{user.name}*. Try `/flockit <ai developer> <what to do>`."


async def _ai_developer(db: AsyncSession, org_id, name: str) -> Optional[User]:
    wanted = name.strip().lstrip("@").lower()
    rows = (
        await db.execute(
            select(User).where(User.org_id == org_id, User.kind == UserKind.ai, User.is_active.is_(True))
        )
    ).scalars().all()
    for u in rows:
        if u.name.lower() == wanted or u.name.lower().split()[0] == wanted:
            return u
    return None


def _split(text: str) -> Tuple[str, str, Optional[str]]:
    """``"ada repo=github.com/acme/api fix the thing"`` -> name, prompt, repo."""
    words = text.strip().split()
    if not words:
        return "", "", None
    name, rest = words[0], words[1:]
    repo = None
    kept = []
    for word in rest:
        if word.startswith("repo=") and repo is None:
            repo = word[5:]
        else:
            kept.append(word)
    return name, " ".join(kept).strip(), repo


async def _status(db: AsyncSession, user: User) -> dict:
    rows = (
        await db.execute(
            select(WorkflowRun)
            .where(WorkflowRun.triggered_by_id == user.id, WorkflowRun.status.in_(ACTIVE_RUN_STATUSES))
            .order_by(WorkflowRun.created_at.desc())
            .limit(10)
        )
    ).scalars().unique().all()
    if not rows:
        return _ephemeral("Nothing running right now.")
    lines = [f"• *{r.title}* — {r.status.value}" + (f" ({r.assignee.name})" if r.assignee else "") for r in rows]
    return _ephemeral("\n".join(lines))


async def handle(db: AsyncSession, slack_user_id: str, text: str, notify: Dict[str, Any]) -> dict:
    """The shared grammar behind both the slash command and an @mention."""
    text = text.strip()
    if not text or text.lower() in ("help", "?"):
        return _ephemeral(HELP)
    first, _, rest = text.partition(" ")
    if first.lower() == "link":
        return _ephemeral(await _link(db, slack_user_id, rest))
    person = await _person(db, slack_user_id)
    if person is None:
        return _ephemeral(
            "This Slack account is not linked to anyone in Flockit yet. "
            "Open Flockit → Connect, copy the code, then run `/flockit link <code>`."
        )
    if first.lower() in ("tasks", "status"):
        return await _status(db, person)

    name, prompt, repo_override = _split(text)
    agent = await _ai_developer(db, person.org_id, name)
    if agent is None:
        return _ephemeral(f"No AI developer called *{name}*. `/flockit help` lists what to type.")
    if not prompt:
        return _ephemeral(f"Tell {agent.name} what to do: `/flockit {name} fix the flaky checkout test`.")
    if not await runs.assignable(db, person, agent):
        return _ephemeral(f"You cannot assign work to {agent.name}.")
    try:
        repo = runs.validate_repo(repo_override or agent.default_repo, for_ai=True)
    except HTTPException:
        return _ephemeral(f"`{repo_override}` is not a repository Flockit is allowed to work in.")
    if not repo:
        return _ephemeral(
            f"{agent.name} has no repository set. Add one in Flockit, or say "
            f"`/flockit {name} repo=github.com/acme/api {prompt[:40]}…`"
        )
    title = prompt.strip().split("\n")[0][:120]
    await runs.create_run(
        db,
        org_id=person.org_id,
        assignee=agent,
        title=title,
        prompt=prompt,
        repo=repo,
        base_branch=None,
        task_ref=None,
        mode=RunMode.auto,
        trigger="slack",
        triggered_by=person,
        # Slack text is written by whoever can type in the channel. create_run applies the
        # same rule as webhooks: work like this never auto-starts on a person's machine.
        notify={"slack": notify},
    )
    await db.commit()
    return {
        "response_type": "in_channel",
        "text": f":robot_face: *{agent.name}* picked up *{title}* in `{repo}`. I'll post the result here.",
    }


@router.post("/command")
async def slash_command(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    raw = await _read(request)
    verify(raw, request)
    form = _form(raw)
    notify = {"channel": form.get("channel_id", ""), "user": form.get("user_id", "")}
    return await handle(db, form.get("user_id", ""), form.get("text", ""), notify)


@router.post("/events")
async def events(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """The Events API, for `@flockit …` in a channel. Slack retries, so replies are best effort
    and the work itself is idempotent per message."""
    raw = await _read(request)
    verify(raw, request)
    try:
        body = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise HTTPException(400, "Not JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(400, "Not an event")
    if body.get("type") == "url_verification":
        return {"challenge": str(body.get("challenge", ""))[:500]}
    event = body.get("event") if isinstance(body.get("event"), dict) else {}
    if event.get("type") != "app_mention" or event.get("bot_id"):
        return {"ok": True}
    # Drop the "<@U123>" that starts a mention; the rest is the command.
    text = re.sub(r"^\s*<@[A-Z0-9]+>\s*", "", str(event.get("text", "")))
    notify = {
        "channel": str(event.get("channel", ""))[:32],
        "thread_ts": str(event.get("thread_ts") or event.get("ts") or "")[:32],
        "user": str(event.get("user", ""))[:32],
    }
    await handle(db, notify["user"], text, notify)
    return {"ok": True}


@router.get("/status")
async def slack_status() -> dict:
    """Whether this deployment can accept Slack commands at all (shown on the Connect page)."""
    return {"configured": bool(get_settings().slack_signing_secret)}


__all__ = ["router", "RunStatus"]
