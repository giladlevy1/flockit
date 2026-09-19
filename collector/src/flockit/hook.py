"""Claude Code hook entry point.

Claude Code runs ``flockit hook`` on SessionStart, UserPromptSubmit, Stop and
SessionEnd, passing a JSON document on stdin. This module turns that into a
redacted event, buffers it locally and hands delivery to a detached process.

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
from typing import Any, Dict, Optional

from flockit import __version__, config, gitinfo, log, outbox, taskref, transcript, transport
from flockit.redact import redact_session

VENDOR = "claude-code"


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
    path.write_text(json.dumps(state))


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
    """Repo, branch and task ref. Computed once per session and cached in local state."""
    if "repo" in state or "branch" in state:
        return state
    repo, branch = gitinfo.repo_and_branch(data.get("cwd"))
    state["repo"] = repo
    state["branch"] = branch
    state["task_ref"] = taskref.from_env() or taskref.from_branch(branch)
    return state


def build_event(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Turn one hook invocation into at most one redacted event. Pure apart from local state."""
    session_id = data.get("session_id")
    hook = data.get("hook_event_name")
    if not isinstance(session_id, str) or not isinstance(hook, str):
        return None

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
            return None  # nothing new to report; Stop carries activity
        ref = taskref.from_prompt(data.get("prompt"))
        if not ref:
            _save_state(session_id, state)
            return None
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
        return None

    if hook in ("Stop", "SessionEnd", "SessionStart"):
        model, version = transcript.model_and_version(data.get("transcript_path"))
        fields["agent_model"] = fields.get("agent_model") or model
        fields["agent_version"] = version

    fields["repo"] = state.get("repo")
    fields["branch"] = state.get("branch")
    fields["task_ref"] = state.get("task_ref")

    if hook == "SessionEnd":
        _drop_state(session_id)
    else:
        _save_state(session_id, state)

    return {
        "event_id": str(uuid.uuid4()),
        "type": kind,
        "occurred_at": _now(),
        "collector_version": __version__,
        "session": redact_session(fields),
    }


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
        if config.load() is None:
            return  # not configured: do nothing, silently
        data = json.loads(stdin_text or "{}")
        if not isinstance(data, dict):
            return
        event = build_event(data)
        if event is None:
            return
        outbox.append(event)
        _spawn_flush()
    except Exception as exc:  # noqa: BLE001 - the hook must never fail a session
        log.write("hook error: %s" % type(exc).__name__)
