"""Read the repo and branch for a working directory. Fast, bounded, never raises."""

from __future__ import annotations

import subprocess
from typing import Optional, Tuple

_TIMEOUT = 1.0


def _git(cwd: str, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    value = out.stdout.strip()
    return value or None


def repo_and_branch(cwd: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(remote_or_toplevel, branch)``. Values are raw; redaction happens later."""
    if not cwd:
        return None, None
    top = _git(cwd, "rev-parse", "--show-toplevel")
    if top is None:
        return None, None
    remote = _git(cwd, "config", "--get", "remote.origin.url")
    # symbolic-ref works on a fresh repo with no commits; it fails when detached.
    branch = _git(cwd, "symbolic-ref", "--short", "-q", "HEAD")
    return remote or top, branch


def toplevel(cwd: Optional[str]) -> Optional[str]:
    return _git(cwd, "rev-parse", "--show-toplevel") if cwd else None
