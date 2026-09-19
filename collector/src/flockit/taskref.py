"""Find the ticket or issue a session is working on.

Sources, in order of precedence:
1. ``FLOCKIT_TASK_REF`` in the environment (explicit beats inferred).
2. The branch name: ``feature/ENG-123-login`` -> ``ENG-123``, ``fix/gh-42`` or ``issue-42`` -> ``#42``.
3. The first prompt that mentions a ticket key or an issue/ticket URL.

Only the extracted reference ever leaves the machine. The prompt itself is read
locally, matched, and discarded.
"""

from __future__ import annotations

import os
import re
from typing import Optional

from flockit.redact import normalize_task_ref

_JIRA_IN_TEXT = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{1,15}-\d{1,7})(?![A-Za-z0-9])")
_ISSUE_BRANCH = re.compile(r"(?:^|[/_\-])(?:gh|issue|issues)[\-_/]?(\d{1,9})(?:$|[/_\-])", re.IGNORECASE)
_ISSUE_URL = re.compile(
    r"https?://[^\s<>()\"'/]{1,253}(?:/[^\s<>()\"'/]{1,100}){0,6}?"
    r"/(?:issues|pull|pulls|merge_requests|browse|tickets?|issue)/[A-Za-z0-9\-]{1,40}",
    re.IGNORECASE,
)
_LINEAR_URL = re.compile(r"https?://linear\.app/[A-Za-z0-9._\-]{1,100}/issue/[A-Za-z0-9\-]{1,40}", re.IGNORECASE)

# Only the start of a prompt is searched. Bounds the work a hook can do on a huge paste.
MAX_PROMPT_CHARS = 4000

# Things that look like ticket keys but are not.
_NOT_TICKETS = {"UTF-8", "UTF-16", "ISO-8859", "SHA-1", "SHA-256", "SHA-512", "HTTP-2", "RFC-2616", "CVE-2024"}


def from_env() -> Optional[str]:
    return normalize_task_ref(os.environ.get("FLOCKIT_TASK_REF"))


def _jira(text: str) -> Optional[str]:
    for match in _JIRA_IN_TEXT.finditer(text):
        key = match.group(1)
        if key in _NOT_TICKETS or key.split("-")[0] in {"UTF", "ISO", "SHA", "HTTP", "RFC", "CVE", "PR", "GH", "ISSUE", "ISSUES", "RELEASE", "V"}:
            continue
        return key
    return None


def from_branch(branch: Optional[str]) -> Optional[str]:
    if not branch:
        return None
    m = _ISSUE_BRANCH.search(branch)
    if m:
        return "#" + m.group(1)
    return _jira(branch.upper())


def from_prompt(prompt: Optional[str]) -> Optional[str]:
    if not prompt:
        return None
    prompt = prompt[:MAX_PROMPT_CHARS]
    for pattern in (_LINEAR_URL, _ISSUE_URL):
        m = pattern.search(prompt)
        if m:
            ref = normalize_task_ref(m.group(0).rstrip(".,;:"))
            if ref:
                return ref
    return _jira(prompt)
