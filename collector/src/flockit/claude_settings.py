"""Register and remove Flockit's hooks in Claude Code's user settings.

Only entries Flockit created are touched. Every other hook and setting in the
file is preserved exactly, and the original file is backed up once.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

EVENTS = ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd")
MARKER = "-m flockit hook"
HOOK_TIMEOUT_SECONDS = 5


def settings_path() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base).expanduser() if base else Path.home() / ".claude") / "settings.json"


def hook_command() -> str:
    # The absolute interpreter path, so the hook works even when the tool's bin
    # directory is not on the PATH Claude Code inherits.
    return "%s %s" % (shlex.quote(sys.executable), MARKER)


def _read(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text().strip()
    if not text:
        return {}
    data = json.loads(text)  # refuse to touch a file we cannot parse
    if not isinstance(data, dict):
        raise ValueError("%s is not a JSON object" % path)
    return data


def _is_ours(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    return any(isinstance(h, dict) and MARKER in str(h.get("command", "")) for h in hooks)


def _without_ours(entries: Any) -> List[Any]:
    if not isinstance(entries, list):
        return []
    return [e for e in entries if not _is_ours(e)]


def _write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(path.name + ".flockit-backup")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)
    tmp = path.with_suffix(".flockit-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def install() -> Path:
    path = settings_path()
    data = _read(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    command = hook_command()
    for event in EVENTS:
        entries = _without_ours(hooks.get(event))
        entries.append({"hooks": [{"type": "command", "command": command, "timeout": HOOK_TIMEOUT_SECONDS}]})
        hooks[event] = entries
    data["hooks"] = hooks
    _write(path, data)
    return path


def uninstall() -> Path:
    path = settings_path()
    data = _read(path)
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        for event in list(hooks):
            remaining = _without_ours(hooks[event]) if isinstance(hooks[event], list) else hooks[event]
            if remaining:
                hooks[event] = remaining
            else:
                del hooks[event]
        if not hooks:
            del data["hooks"]
        _write(path, data)
    return path


def installed() -> bool:
    try:
        data = _read(settings_path())
    except (OSError, ValueError):
        return False
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    return all(any(_is_ours(e) for e in hooks.get(event) or []) for event in EVENTS)
