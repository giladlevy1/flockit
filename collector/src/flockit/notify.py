"""Posting a finished task back to where it was asked for.

Flockit's server makes no outbound calls, so it cannot answer Slack itself. The runner
can: it already reaches the model provider and the git host. A task that came from Slack
carries ``notify: {"slack": {"channel": …, "thread_ts": …}}``, and when the work is done
the runner posts the result into that thread with its own bot token.

Set ``SLACK_BOT_TOKEN`` on the runner to switch this on. Without it, tasks still run and
the result is in Flockit; it just is not announced.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from flockit import __version__, log
from flockit.redact import scrub

SLACK_API = "https://slack.com/api/chat.postMessage"
MAX_TEXT = 2_500


def _summary(status: str, title: str, agent: str, result: Optional[str], error: Optional[str], pr_url: Optional[str],
             session_url: Optional[str]) -> str:
    icon = {"succeeded": ":white_check_mark:", "failed": ":x:", "cancelled": ":black_square_for_stop:"}.get(status, ":hourglass:")
    lines = [f"{icon} *{agent}* — {title}"]
    body = (result or error or "").strip()
    if body:
        lines.append(scrub(body)[:MAX_TEXT])
    if pr_url:
        lines.append(f"Pull request: {pr_url}")
    if session_url:
        lines.append(f"Session: {session_url}")
    return "\n".join(lines)


def slack(token: str, notify: Dict[str, Any], text: str) -> bool:
    """One ``chat.postMessage``. Never raises: an announcement is not worth failing a task for."""
    channel = str(notify.get("channel") or "")
    if not token or not channel:
        return False
    payload: Dict[str, Any] = {"channel": channel, "text": text[:3900], "unfurl_links": False}
    if notify.get("thread_ts"):
        payload["thread_ts"] = str(notify["thread_ts"])
    request = urllib.request.Request(SLACK_API, data=json.dumps(payload).encode(), method="POST")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json; charset=utf-8")
    request.add_header("User-Agent", f"flockit-runner/{__version__}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read() or b"{}")
        if not body.get("ok"):
            log.write(f"slack: {body.get('error')}")
        return bool(body.get("ok"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.write(f"slack: {exc}")
        return False


def task_finished(
    token: str,
    task: Dict[str, Any],
    status: str,
    *,
    result: Optional[str] = None,
    error: Optional[str] = None,
    pr_url: Optional[str] = None,
    server_url: Optional[str] = None,
) -> bool:
    notify = (task.get("notify") or {}).get("slack") if isinstance(task.get("notify"), dict) else None
    if not isinstance(notify, dict):
        return False
    session_url = f"{server_url.rstrip('/')}/tasks?task={task['id']}" if server_url else None
    agent = (task.get("agent") or {}).get("name", "AI developer")
    return slack(token, notify, _summary(status, task.get("title", "task"), agent, result, error, pr_url, session_url))
