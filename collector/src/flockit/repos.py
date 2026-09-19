"""Where each repository lives on this machine. Kept locally in ``~/.flockit/repos.json``
and never sent: it lets the agent start a task in the right checkout."""

from __future__ import annotations

import json
import os
from typing import Dict, Optional

from flockit import config


def _path():
    return config.home() / "repos.json"


def load() -> Dict[str, str]:
    try:
        data = json.loads(_path().read_text())
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
    except (OSError, ValueError, AttributeError):
        return {}


def remember(repo: str, root: str) -> None:
    known = load()
    if known.get(repo) == root:
        return
    known[repo] = root
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(known, indent=2, sort_keys=True))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def find(repo: Optional[str]) -> Optional[str]:
    if not repo:
        return None
    root = load().get(repo)
    return root if root and os.path.isdir(root) else None
