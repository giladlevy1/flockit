"""Workspaces for tasks: a fresh git worktree on the task's branch, so an agent never
touches the developer's own checkout or uncommitted work."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from flockit import config, repos


class WorkspaceError(RuntimeError):
    pass


def _git(args: List[str], cwd: Optional[str] = None, timeout: int = 120) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkspaceError(f"git {args[0]} failed: {exc}") from exc
    if out.returncode != 0:
        raise WorkspaceError(f"git {args[0]} failed: {out.stderr.strip()[-500:]}")
    return out.stdout.strip()


_REPO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~\-]+){1,6}$")
_LOCAL = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._\-]{0,99}$")


def check_repo(repo: str) -> str:
    """Accept ``host/owner/name`` or a plain local name. Reject anything git could read as an
    option or a path (``..``, leading dashes, URLs, absolute paths)."""
    repo = (repo or "").strip()
    segments = repo.split("/")
    if any(seg in ("", ".", "..") or seg.startswith("-") for seg in segments) or "://" in repo:
        raise WorkspaceError(f"Not a valid repository: {repo!r}")
    if not (_REPO.match(repo) or _LOCAL.match(repo)):
        raise WorkspaceError(f"Not a valid repository: {repo!r}")
    return repo


def remote_urls(repo: str) -> List[str]:
    """``github.com/acme/api`` -> HTTPS and SSH clone URLs to try, in that order."""
    host, _, path = repo.partition("/")
    if not host or not path:
        return []
    return [f"https://{host}/{path}.git", f"git@{host}:{path}.git"]


def clone_root() -> Path:
    override = os.environ.get("FLOCKIT_WORKSPACES")
    return Path(override).expanduser() if override else Path.home() / "flockit-workspaces"


def find_or_clone(repo: str) -> str:
    """The developer's checkout if Flockit has seen one, otherwise a clone made with their own git credentials."""
    repo = check_repo(repo)
    known = repos.find(repo)
    if known:
        return known
    target = clone_root() / re.sub(r"[^A-Za-z0-9._-]+", "__", repo)
    if (target / ".git").exists():
        return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for url in remote_urls(repo):
        try:
            _git(["clone", "--quiet", "--", url, str(target)], timeout=600)
            repos.remember(repo, str(target))
            return str(target)
        except WorkspaceError as exc:
            errors.append(str(exc))
            shutil.rmtree(target, ignore_errors=True)
    raise WorkspaceError(
        f"Could not find {repo} on this machine or clone it. Open it once with Claude Code, or check your git access. "
        + (errors[-1] if errors else "")
    )


def _base_ref(root: str, base_branch: Optional[str]) -> str:
    try:
        _git(["fetch", "--quiet", "origin"], cwd=root, timeout=120)
    except WorkspaceError:
        pass  # offline: work from what we have
    candidates = []
    if base_branch:
        candidates += [f"origin/{base_branch}", base_branch]
    try:
        head = _git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=root)
        candidates.append(head)
    except WorkspaceError:
        pass
    candidates.append("HEAD")
    for ref in candidates:
        try:
            _git(["rev-parse", "--verify", "--quiet", ref], cwd=root)
            return ref
        except WorkspaceError:
            continue
    raise WorkspaceError("The repository has no commits to branch from")


def worktrees_dir() -> Path:
    return config.home() / "worktrees"


def prepare(repo: Optional[str], base_branch: Optional[str], branch: str, task_id: str) -> str:
    """A worktree for the task, on ``branch``. Reuses it if the task is started again."""
    if not repo:
        raise WorkspaceError("The task has no repository")
    if base_branch and (base_branch.startswith("-") or ".." in base_branch):
        raise WorkspaceError(f"Not a valid base branch: {base_branch!r}")
    root = find_or_clone(repo)
    leaf = re.sub(r"[^A-Za-z0-9._-]+", "-", branch.split("/")[-1])[:48]
    path = worktrees_dir() / (leaf if leaf.startswith(task_id[:8]) else f"{task_id[:8]}-{leaf}")
    if (path / ".git").exists():
        return str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=root)
        _git(["worktree", "add", "--quiet", str(path), branch], cwd=root)
    except WorkspaceError:
        _git(["worktree", "add", "--quiet", "-b", branch, str(path), _base_ref(root, base_branch), "--"], cwd=root)
    return str(path)
