"""Always-on sessions: keeping a session continuable after the machine goes away.

Closing a laptop does not end a Claude Code session. It just stops: no Stop hook, no
SessionEnd, the work simply freezes mid-thought with uncommitted changes in the tree.

So while a session is live, the agent takes a snapshot of the working tree every minute
and pushes it to a shadow ref. If the machine then disappears, Flockit can hand the work
to the developer's own AI developer, which starts from exactly those files.

The snapshot never touches anything the developer can see:

- a **temporary index file**, so `git status` and anything they have staged are untouched
- `commit-tree` against HEAD, so no commit is ever added to their branch
- `refs/flockit/wip/<session>`, not a branch, so it does not appear in their branch list,
  does not move HEAD, and does not trigger CI on the remote

If anything goes wrong — no git, a detached HEAD, no remote, no credentials — the
snapshot is skipped and the session carries on as it always has.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from typing import Dict, Optional

from flockit import log

SNAPSHOT_EVERY_SECONDS = 60
GIT_TIMEOUT = 60
# Session ids come from Claude Code (UUIDs); anything else never reaches a ref name.
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")


def ref_for(session_id: str) -> str:
    return f"refs/flockit/wip/{session_id}"


def _git(args, cwd: str, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    """Run git, and treat "could not run git" the same as "git said no".

    The agent runs under launchd or systemd with a minimal environment, so git may simply
    not be on PATH. A snapshot is a background nicety: it fails quietly and the session
    carries on exactly as it would have without it.
    """
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})},
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.write(f"snapshot: git {args[0]} unavailable ({type(exc).__name__})")
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr=str(exc))


def snapshot(root: str, session_id: str) -> Optional[Dict[str, object]]:
    """Record the working tree as a commit on a shadow ref. Returns what was recorded.

    Returns ``None`` when there is nothing to snapshot or git cannot do it safely.
    """
    if not SAFE_ID.match(session_id) or not os.path.isdir(root):
        return None
    head = _git(["rev-parse", "HEAD"], root)
    if head.returncode != 0:
        return None  # an empty repository has nothing to continue from
    parent = head.stdout.strip()

    with tempfile.TemporaryDirectory(prefix="flockit-wip-") as tmp:
        index = os.path.join(tmp, "index")
        # A temporary index: the developer's staged changes are not read or written.
        env = {"GIT_INDEX_FILE": index}
        if _git(["read-tree", parent], root, env).returncode != 0:
            return None
        # Everything in the tree, including files they have not staged. Ignored files stay ignored.
        if _git(["add", "-A", "--", "."], root, env).returncode != 0:
            return None
        tree = _git(["write-tree"], root, env)
        if tree.returncode != 0:
            return None
        tree_sha = tree.stdout.strip()

    made = _git(
        ["commit-tree", tree_sha, "-p", parent, "-m", f"flockit: work in progress ({session_id[:8]})"],
        root,
        {"GIT_AUTHOR_NAME": "Flockit", "GIT_AUTHOR_EMAIL": "agent@flockit.local",
         "GIT_COMMITTER_NAME": "Flockit", "GIT_COMMITTER_EMAIL": "agent@flockit.local"},
    )
    if made.returncode != 0:
        return None
    sha = made.stdout.strip()
    ref = ref_for(session_id)
    if _git(["update-ref", ref, sha], root).returncode != 0:
        return None
    return {"ref": ref, "sha": sha, "pushed": push(root, ref, sha), "parent": parent}


def push(root: str, ref: str, sha: str) -> bool:
    """Send the snapshot to the repository's remote, using the developer's own git access.

    A shadow ref, force-updated: it is a snapshot, not history. Failure is normal and
    quiet — no remote, no credentials, or a server that refuses these refs — and it only
    means the work cannot be picked up elsewhere yet.
    """
    if _git(["remote", "get-url", "origin"], root).returncode != 0:
        return False  # nothing to push to

    out = _git(["push", "--quiet", "--force", "origin", f"{sha}:{ref}"], root)
    if out.returncode != 0:
        log.write(f"wip push skipped: {out.stderr.strip()[:160]}")
    return out.returncode == 0


def cleanup(root: str, session_id: str) -> None:
    """Drop the shadow ref once a session has ended and been dealt with."""
    if SAFE_ID.match(session_id):
        _git(["update-ref", "-d", ref_for(session_id)], root)
