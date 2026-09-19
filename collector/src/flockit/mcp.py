"""``flockit mcp``: the org's engineering memory, inside the editor.

Every Claude Code session in the org is already captured. This turns that into something
the *next* session can use: from inside Claude Code you can ask what has already been
tried, read how a bug was fixed six weeks ago by someone on another team, see what an AI
developer changed last night, and hand work off without leaving the terminal.

It speaks MCP over stdio (JSON-RPC 2.0), so Claude Code, Codex and anything else that
speaks MCP can use it:

    flockit mcp install          # registers this server with Claude Code
    flockit mcp serve            # what the editor runs

Scope is the server's, not the client's: an MCP token acts as its owner, so a developer
sees their own sessions, a lead their teams', an admin the organisation. Nothing here can
widen that — the API applies the same rules it applies to the web UI.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

from flockit import __version__, config, transport

PROTOCOL = "2025-06-18"
TIMEOUT = 20.0
MAX_CHARS = 30_000


class NotConfigured(RuntimeError):
    pass


def _cfg() -> config.Config:
    cfg = config.load()
    if cfg is None:
        raise NotConfigured("Flockit is not set up on this machine. Run the install command from Flockit → Connect.")
    if not cfg.mcp_token:
        raise NotConfigured(
            "No editor token yet. In Flockit → Connect, create an editor (MCP) token, then run:\n"
            "  flockit mcp install --token <token>"
        )
    return config.Config(server_url=cfg.server_url, token=cfg.mcp_token)


def _get(path: str, **params: Any) -> Any:
    """A read against the Flockit API as this person. Errors come back as text, not crashes."""
    query = "&".join(
        f"{k}={_quote(str(v))}" for k, v in params.items() if v is not None and v != "" and v != []
    )
    result = transport.request(_cfg(), "GET", path + ("?" + query if query else ""), timeout=TIMEOUT)
    if not result.ok:
        if result.status == 401:
            raise NotConfigured("The editor token was rejected. Create a new one in Flockit → Connect.")
        detail = (result.body or {}).get("detail") if isinstance(result.body, dict) else None
        raise RuntimeError(detail or result.error or f"Flockit returned {result.status}")
    return result.body


def _post(path: str, payload: Dict[str, Any]) -> Any:
    cfg = _cfg()
    result = transport.request(cfg, "POST", path, payload, timeout=TIMEOUT)
    if not result.ok:
        detail = (result.body or {}).get("detail") if isinstance(result.body, dict) else None
        raise RuntimeError(detail or result.error or f"Flockit returned {result.status}")
    return result.body


def _quote(value: str) -> str:
    import urllib.parse

    return urllib.parse.quote(value, safe="")


def _clip(text: str) -> str:
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n… (truncated)"


def _who(*candidates: Any) -> str:
    """People come back as a name or as {id, name}: this reads either."""
    for value in candidates:
        if isinstance(value, dict) and value.get("name"):
            return str(value["name"])
        if isinstance(value, str) and value.strip():
            return value
    return "someone"


# --- tools ---------------------------------------------------------------------------


def search_sessions(query: str, limit: int = 10) -> str:
    body = _get("/api/search", q=query, limit=min(int(limit), 25)) or {}
    items = body.get("items") or []
    if not items:
        return f"No sessions mention {query!r} in what you can see."
    lines = [f"{len(items)} match(es) for {query!r}:"]
    for hit in items:
        session = hit.get("session") or {}
        who = _who(session.get("actor"), session.get("owner"))
        lines.append(
            f"\n• [{hit.get('session_id')}] {session.get('title') or 'Untitled'}"
            f"\n  {who}, {session.get('repo') or 'no repo'}, {str(hit.get('at') or '')[:10]}"
            f"\n  …{(hit.get('snippet') or '').replace('<<', '**').replace('>>', '**')}…"
        )
    lines.append("\nUse get_session with an id to read one in full.")
    return _clip("\n".join(lines))


def get_session(session_id: str, messages: int = 60) -> str:
    session = _get(f"/api/sessions/{_quote(session_id)}") or {}
    body = _get(f"/api/sessions/{_quote(session_id)}/transcript", limit=min(int(messages), 200)) or {}
    actor = _who(session.get("actor"), session.get("owner"))
    head = [
        f"# {session.get('title') or 'Untitled session'}",
        f"{actor} · {session.get('repo') or 'no repo'} · {str(session.get('started_at') or '')[:16]}"
        f" · {session.get('turn_count', 0)} turns · {session.get('files_touched', 0)} files"
        f" · {session.get('outcome') or 'running'}",
        "",
    ]
    for m in body.get("items") or []:
        role = {"user": "Developer", "assistant": "Agent"}.get(m.get("role"), m.get("role", "?"))
        if m.get("kind") == "tool_use":
            head.append(f"[{m.get('tool_name') or 'tool'}] {m.get('content', '')[:600]}")
        elif m.get("kind") == "tool_result":
            head.append(f"[result] {m.get('content', '')[:400]}")
        else:
            head.append(f"**{role}:** {m.get('content', '')[:2000]}")
    return _clip("\n".join(head))


def recent_sessions(repo: Optional[str] = None, person: Optional[str] = None, limit: int = 15) -> str:
    body = _get("/api/sessions", repo=repo, q=person, limit=min(int(limit), 50)) or {}
    items = body.get("items") or []
    if not items:
        return "No sessions match."
    lines = []
    for s in items:
        who = _who(s.get("actor"), s.get("owner"))
        lines.append(
            f"• [{s.get('id')}] {s.get('title') or 'Untitled'} — {who}, {s.get('repo') or 'no repo'}, "
            f"{str(s.get('started_at') or '')[:16]}, {s.get('outcome') or 'running'}"
        )
    return _clip("\n".join(lines))


def ai_developers() -> str:
    rows = _get("/api/ai-developers") or []
    if not rows:
        return "This organisation has no AI developers yet."
    lines = []
    for a in rows:
        env = (a.get("environment") or {}).get("name")
        tasks = a.get("stats", {}).get("tasks", {})
        done = tasks.get("succeeded", 0)
        lines.append(
            f"• {a['name']} ({a.get('agent_vendor')}) — {done} task(s) done"
            + (f", workbench {env}" if env else "")
            + (f", repo {a.get('default_repo')}" if a.get("default_repo") else "")
            + (f", busy with: {a['current_task']['title']}" if a.get("current_task") else "")
            + f"\n  id: {a['id']}"
        )
    return _clip("\n".join(lines))


def ai_developer(developer_id: str) -> str:
    body = _get(f"/api/ai-developers/{_quote(developer_id)}") or {}
    dev = body.get("developer") or {}
    lines = [f"# {dev.get('name')}", ""]
    env = dev.get("environment")
    if env:
        services = ", ".join(s.get("name", "?") for s in env.get("services") or []) or "none"
        lines += [f"Workbench **{env.get('name')}** ({services}): {env.get('description') or ''}", ""]
    expertise = body.get("expertise") or {}
    if expertise.get("repos"):
        lines.append("Repositories: " + ", ".join(f"{r['repo']} ({r['tasks']})" for r in expertise["repos"]))
    if expertise.get("areas"):
        lines.append("Areas edited: " + ", ".join(f"{a['area']} ({a['files']})" for a in expertise["areas"]))
    lines.append("")
    for t in (body.get("tasks") or [])[:10]:
        lines.append(f"• {t['status']}: {t['title']}" + (f" → {t['pr_url']}" if t.get("pr_url") else ""))
    return _clip("\n".join(lines))


def my_tasks() -> str:
    body = _get("/api/tasks", view="mine", limit=25) or {}
    items = body.get("items") or []
    if not items:
        return "Nothing assigned to you."
    return _clip(
        "\n".join(
            f"• [{t['status']}] {t['title']}" + (f" — {t['repo']}" if t.get("repo") else "") + f"  (id {t['id']})"
            for t in items
        )
    )


def assign_task(assignee_id: str, title: str, prompt: str, repo: Optional[str] = None) -> str:
    """Hand work to an AI developer (or a teammate) without leaving the session."""
    body = _post(
        "/api/tasks",
        {"assignee_id": assignee_id, "title": title[:300], "prompt": prompt, "repo": repo},
    ) or {}
    who = (body.get("assignee") or {}).get("name", "them")
    return f"Assigned to {who}: {body.get('title')} ({body.get('status')}). Task id {body.get('id')}."


TOOLS: List[Tuple[str, str, dict, Callable[..., str]]] = [
    (
        "search_sessions",
        "Search every Claude Code and AI-developer session you are allowed to see, by what was said, "
        "run or edited. Use this before solving something that may already have been solved.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words to look for, e.g. 'checkout race condition'"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        search_sessions,
    ),
    (
        "get_session",
        "Read one session end to end: the prompts, the agent's replies, the commands it ran and the files it touched.",
        {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "messages": {"type": "integer", "default": 60},
            },
            "required": ["session_id"],
        },
        get_session,
    ),
    (
        "recent_sessions",
        "The latest sessions, optionally for one repository or person. Good for 'what has the team been doing here?'",
        {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "person": {"type": "string", "description": "Name to filter by"},
                "limit": {"type": "integer", "default": 15},
            },
        },
        recent_sessions,
    ),
    (
        "ai_developers",
        "List the organisation's AI developers, what they are working on and which workbench each one has.",
        {"type": "object", "properties": {}},
        ai_developers,
    ),
    (
        "ai_developer",
        "One AI developer in detail: its workbench, the repositories and areas it knows, and its recent tasks.",
        {"type": "object", "properties": {"developer_id": {"type": "string"}}, "required": ["developer_id"]},
        ai_developer,
    ),
    (
        "my_tasks",
        "Tasks assigned to you in Flockit.",
        {"type": "object", "properties": {}},
        my_tasks,
    ),
    (
        "assign_task",
        "Give a piece of work to an AI developer (use ai_developers for ids). It runs in their sandbox and "
        "reports back in Flockit.",
        {
            "type": "object",
            "properties": {
                "assignee_id": {"type": "string", "description": "AI developer id from ai_developers"},
                "title": {"type": "string"},
                "prompt": {"type": "string", "description": "What to do, as you would tell a colleague"},
                "repo": {"type": "string", "description": "host/owner/name; defaults to the AI developer's repository"},
            },
            "required": ["assignee_id", "title", "prompt"],
        },
        assign_task,
    ),
]

BY_NAME = {name: (schema, fn) for name, _, schema, fn in TOOLS}


# --- JSON-RPC over stdio ---------------------------------------------------------------


def _result(request_id: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _text(body: str, is_error: bool = False) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": body}], "isError": is_error}


def handle(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One JSON-RPC message in, at most one out (notifications get no reply)."""
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _result(
            request_id,
            {
                "protocolVersion": asked if isinstance(asked, str) and asked else PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "flockit", "version": __version__},
                "instructions": (
                    "Flockit holds every coding session in this organisation. Search it before starting "
                    "work that someone may have done already, and hand work to an AI developer with assign_task."
                ),
            },
        )
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(
            request_id,
            {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s, _ in TOOLS]},
        )
    if method == "tools/call":
        name = params.get("name")
        entry = BY_NAME.get(name)
        if entry is None:
            return _result(request_id, _text(f"No such tool: {name}", True))
        _, fn = entry
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _result(request_id, _text("Arguments must be an object", True))
        try:
            return _result(request_id, _text(fn(**arguments)))
        except TypeError as exc:
            return _result(request_id, _text(f"Wrong arguments for {name}: {exc}", True))
        except (NotConfigured, RuntimeError) as exc:
            return _result(request_id, _text(str(exc), True))
    if request_id is None:
        return None
    return _error(request_id, -32601, f"Unknown method: {method}")


def serve(stdin=None, stdout=None) -> int:
    """Read line-delimited JSON-RPC from stdin until it closes."""
    source = stdin or sys.stdin
    sink = stdout or sys.stdout
    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict):
            continue
        try:
            reply = handle(message)
        except Exception as exc:  # noqa: BLE001 - a tool bug must not kill the editor's server
            reply = _error(message.get("id"), -32603, f"{type(exc).__name__}: {exc}")
        if reply is not None:
            sink.write(json.dumps(reply) + "\n")
            sink.flush()
    return 0
