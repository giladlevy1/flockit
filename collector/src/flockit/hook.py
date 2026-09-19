"""Claude Code hook entry point.

Claude Code runs ``flockit hook`` on SessionStart, UserPromptSubmit, Stop and
SessionEnd, passing a JSON document on stdin. This module turns that into redacted
events (session metadata, and on Stop/SessionEnd the new part of the transcript),
buffers them locally and hands delivery to a detached process.

Rules this module must never break:
- Never print to stdout. For SessionStart and UserPromptSubmit, Claude Code
  injects hook stdout into the model's context.
- Never exit non-zero and never raise. A broken collector must not break a session.
- Never wait on the network. Delivery happens in a detached ``flockit flush``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from flockit import __version__, config, conversation, gitinfo, log, outbox, repos, taskref, transcript, transport
from flockit.redact import normalize_repo, redact_session

VENDOR = "claude-code"
MESSAGES_PER_EVENT = 250


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_file(session_id: str) -> Path:
    return config.state_dir() / (session_id + ".json")


def _load_state(session_id: str) -> Dict[str, Any]:
    try:
        return json.loads(_state_file(session_id).read_text())
    except (OSError, ValueError):
        return {}


def _save_state(session_id: str, state: Dict[str, Any]) -> None:
    path = _state_file(session_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(path)


def _drop_state(session_id: str) -> None:
    try:
        _state_file(session_id).unlink()
    except OSError:
        pass


def _model_from_input(data: Dict[str, Any]) -> Optional[str]:
    model = data.get("model")
    if isinstance(model, dict):
        model = model.get("id") or model.get("name")
    return model if isinstance(model, str) else None


def _context(data: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    """Repo, branch, task ref and task id. Computed once per session, cached locally."""
    if "repo" in state or "branch" in state:
        return state
    cwd = data.get("cwd")
    repo, branch = gitinfo.repo_and_branch(cwd)
    state["repo"] = repo
    state["branch"] = branch
    state["root"] = gitinfo.toplevel(cwd) if cwd else None
    state["task_ref"] = taskref.from_env() or taskref.from_branch(branch)
    task_id = os.environ.get("FLOCKIT_TASK_ID")
    state["task_id"] = task_id if task_id else None
    # Remember where this repo lives on disk, so the agent can run tasks in it. Local only.
    normalized = normalize_repo(repo)
    if normalized and state["root"]:
        repos.remember(normalized, state["root"])
    return state


def _envelope(kind: str, fields: Dict[str, Any], transcript_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    event = {
        "event_id": str(uuid.uuid4()),
        "type": kind,
        "occurred_at": _now(),
        "collector_version": __version__,
        "session": redact_session(fields),
    }
    if transcript_payload is not None:
        event["transcript"] = transcript_payload
    return event


def _transcript_events(data: Dict[str, Any], state: Dict[str, Any], ids: Dict[str, Any], final: bool) -> List[Dict[str, Any]]:
    """Everything appended to the transcript since the last hook, as redacted events."""
    path = data.get("transcript_path")
    if not isinstance(path, str):
        return []
    tstate = state.get("transcript") or {}
    offset = int(tstate.get("offset", 0))
    converter = conversation.Converter(state.get("root"), tstate.get("converter"))
    batch = conversation.Batch()
    for _ in range(8 if final else 1):  # at session end, drain up to 32 MB
        entries, offset = conversation.read_new(path, offset)
        if not entries:
            break
        converter.feed(entries, batch)
    state["transcript"] = {"offset": offset, "converter": converter.state()}
    if batch.empty():
        return []
    events = []
    messages = batch.messages
    first = True
    while first or messages:
        chunk, messages = messages[:MESSAGES_PER_EVENT], messages[MESSAGES_PER_EVENT:]
        payload = {"title": batch.title, "messages": chunk, "usage": batch.usage, "files": []}
        if first:
            payload["files"] = [{"path": p, "edits": n} for p, n in batch.files.items()]
        else:
            payload["usage"] = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
            payload["title"] = None
        events.append(_envelope("session.transcript", ids, payload))
        first = False
    return events


def build_events(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Turn one hook invocation into redacted events. Pure apart from local state."""
    session_id = data.get("session_id")
    hook = data.get("hook_event_name")
    if not isinstance(session_id, str) or not isinstance(hook, str):
        return []

    state = _load_state(session_id)
    fields: Dict[str, Any] = {"external_id": session_id, "agent_vendor": VENDOR, "origin": "human"}

    if hook == "SessionStart":
        state = _context(data, {})
        kind = "session.start"
        fields["start_source"] = data.get("source")
        fields["agent_model"] = _model_from_input(data)
    elif hook == "UserPromptSubmit":
        state = _context(data, state)
        if state.get("task_ref"):
            _save_state(session_id, state)
            return []  # nothing new to report; Stop carries activity and the transcript
        ref = taskref.from_prompt(data.get("prompt"))
        if not ref:
            _save_state(session_id, state)
            return []
        state["task_ref"] = ref
        kind = "session.update"
    elif hook == "Stop":
        state = _context(data, state)
        kind = "session.activity"
    elif hook == "SessionEnd":
        state = _context(data, state)
        kind = "session.end"
        fields["end_reason"] = data.get("reason")
    else:
        return []

    if hook in ("Stop", "SessionEnd", "SessionStart"):
        model, version = transcript.model_and_version(data.get("transcript_path"))
        fields["agent_model"] = fields.get("agent_model") or model
        fields["agent_version"] = version

    fields["repo"] = state.get("repo")
    fields["branch"] = state.get("branch")
    fields["task_ref"] = state.get("task_ref")
    fields["task_id"] = state.get("task_id")
    ids = {k: fields[k] for k in ("external_id", "agent_vendor", "origin", "task_id")}

    events = []
    if hook in ("Stop", "SessionEnd"):
        # The transcript goes first so a session-end event always follows its content.
        events.extend(_transcript_events(data, state, ids, final=hook == "SessionEnd"))
    events.append(_envelope(kind, fields))

    if hook == "SessionEnd":
        _drop_state(session_id)
    else:
        _save_state(session_id, state)
    return events


def build_event(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The session-metadata event only (kept for callers that want one event)."""
    events = [e for e in build_events(data) if e["type"] != "session.transcript"]
    return events[-1] if events else None


def _spawn_flush() -> None:
    if os.environ.get("FLOCKIT_SYNC") == "1":
        cfg = config.load()
        if cfg:
            transport.flush(cfg)
        return
    subprocess.Popen(
        [sys.executable, "-m", "flockit", "flush", "--quiet"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def run(stdin_text: str) -> None:
    try:
        if os.environ.get("FLOCKIT_DISABLE_HOOK") == "1" or config.load() is None:
            return  # disabled (a runner reports this session itself) or not configured
        data = json.loads(stdin_text or "{}")
        if not isinstance(data, dict):
            return
        events = build_events(data)
        if not events:
            return
        for event in events:
            outbox.append(event)
        _spawn_flush()
    except Exception as exc:  # noqa: BLE001 - the hook must never fail a session
        log.write("hook error: %s" % type(exc).__name__)
