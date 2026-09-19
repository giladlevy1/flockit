"""Local redaction. Runs on the developer's machine before anything is transmitted.

This module is the security boundary of the collector. It works in two layers:

1. **Allowlist.** Only fields named in ``SESSION_FIELDS`` ever leave the machine.
   Each field has a validator that normalises the value or rejects it. Anything
   not on the list is dropped, so a new field in Claude Code's hook payload can
   never leak by accident.
   (The conversation itself travels separately, through ``conversation.py``,
   which runs every piece of text through the same ``scrub()``.)
2. **Scrub.** Every surviving string is passed through ``scrub()``, which
   replaces anything that looks like a credential with ``[REDACTED]``. This is
   defence in depth: the allowlisted fields should never contain secrets, but a
   branch name or a task reference is free text typed by a human.

Session metadata never contains prompts, file paths or environment variables:
they are not on the allowlist, so they cannot be sent that way.
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

REDACTED = "[REDACTED]"

# --- Secret patterns ---------------------------------------------------------
# Ordered: the most specific patterns run first so they win over generic ones.
#
# Boundaries use (?<![A-Za-z0-9]) rather than \b, because \b treats "_" as a word
# character: with \b, "hotfix_sk_live_..." or "x_ghp_..." would slip through.
# Every quantifier that can meet attacker-sized input is bounded, so a pasted
# 16 KB prompt cannot stall a hook with regex backtracking.

_L = r"(?<![A-Za-z0-9])"
_R = r"(?![A-Za-z0-9])"

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]{0,40}PRIVATE KEY-----|$)",
    re.DOTALL,
)

_TOKEN_PATTERNS = [
    # Anthropic, OpenAI and similar "sk-" style keys (sk-ant-..., sk-proj-..., sk-...)
    re.compile(_L + r"sk-(?:ant-|proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{16,}"),
    # Stripe
    re.compile(_L + r"(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}"),
    re.compile(_L + r"whsec_[A-Za-z0-9]{16,}"),
    # AWS access key ids
    re.compile(_L + r"(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA|AIPA)[A-Z0-9]{16}" + _R),
    # GitHub tokens
    re.compile(_L + r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(_L + r"github_pat_[A-Za-z0-9_]{20,}"),
    # GitLab
    re.compile(_L + r"glpat-[A-Za-z0-9_\-]{16,}"),
    # Slack (bot, user, app-level, refresh, config tokens) and webhooks
    re.compile(_L + r"xox[a-z]-[A-Za-z0-9\-]{10,}"),
    re.compile(_L + r"xapp-[0-9]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]+"),
    # Google API key
    re.compile(_L + r"AIza[0-9A-Za-z_\-]{35}"),
    # npm, PyPI, Hugging Face, SendGrid, Twilio, DigitalOcean
    re.compile(_L + r"npm_[A-Za-z0-9]{30,}"),
    re.compile(_L + r"pypi-[A-Za-z0-9_\-]{30,}"),
    re.compile(_L + r"hf_[A-Za-z0-9]{30,}"),
    re.compile(_L + r"SG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}"),
    re.compile(_L + r"SK[0-9a-fA-F]{32}" + _R),
    re.compile(_L + r"do[pr]_v1_[a-f0-9]{64}"),
    # Flockit's own collector tokens
    re.compile(_L + r"flk_[A-Za-z0-9_\-]{16,}"),
    # JSON Web Tokens
    re.compile(_L + r"eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
]

# Authorization headers: "Bearer <token>", "Basic <b64>", "token <token>"
_AUTH_HEADER = re.compile(r"\b(Bearer|Basic|Token)\s{1,8}[A-Za-z0-9_\-\.=+/]{8,}", re.IGNORECASE)

# Credentials embedded in a URL: scheme://user:password@host
_URL_USERINFO = re.compile(r"\b([a-z][a-z0-9+\-.]{0,30}://)[^/\s:@]{0,256}:[^/\s@]{0,256}@", re.IGNORECASE)
# Token-only userinfo: https://ghp_xxx@github.com
_URL_TOKEN_USERINFO = re.compile(r"\b([a-z][a-z0-9+\-.]{0,30}://)[^/\s@:]{16,256}@", re.IGNORECASE)

# Sensitive query-string parameters
_QUERY_SECRET = re.compile(
    r"([?&](?:access_token|refresh_token|id_token|token|api[_-]?key|apikey|key|secret|"
    r"client_secret|password|passwd|pwd|sig|signature|auth|code|X-Amz-Signature|X-Amz-Credential)=)"
    r"[^&#\s]+",
    re.IGNORECASE,
)

# KEY=value / KEY: value where the key name says it is secret
_SECRET_NAME = (
    r"[A-Za-z0-9_\-]{0,64}(?:SECRET|PASSWORD|PASSWD|PWD|TOKEN|API[_\-]?KEY|APIKEY|ACCESS[_\-]?KEY|"
    r"PRIVATE[_\-]?KEY|CREDENTIAL|AUTH|SESSION[_\-]?KEY|DSN|CONN(?:ECTION)?[_\-]?STR(?:ING)?|"
    r"DATABASE[_\-]?URL)[A-Za-z0-9_\-]{0,64}"
)
_ASSIGNMENT = re.compile(
    r"(?P<key>" + _L + _SECRET_NAME + r")(?P<sep>\s{0,8}=>\s{0,8}|\s{0,8}[=:]\s{0,8})(?P<q>[\"']?)(?P<val>[^\s\"'&,;]+)(?P=q)",
    re.IGNORECASE,
)

# Unrecognised formats. Long hex runs (API keys, hashes) are always redacted.
# Other long runs are redacted when they look random rather than like words, so
# "feature/improve-session-list-filters" survives but a URL-safe token does not.
_LONG_HEX = re.compile(_L + r"[A-Fa-f0-9]{32,}" + _R)
_CANDIDATE = re.compile(r"[A-Za-z0-9+/_\-]{24,}={0,2}")
_WORDY = re.compile(
    r"[a-z]{1,20}|[A-Z]{1,12}|[0-9]{1,10}"  # word, ACRONYM, number
    r"|[A-Z]{0,6}(?:[A-Z][a-z]{1,20}){1,6}|[a-z]{1,20}(?:[A-Z][a-z]{1,20}){1,6}"  # CamelCase, camelCase, CSVExport
    r"|[A-Za-z]{1,12}[0-9]{1,4}[a-z]{0,8}"  # utf8, OAuth2, e2e
    r"|v?[0-9]{1,4}(?:\.[0-9]{1,4}){1,3}"  # versions
)


def _entropy(s: str) -> float:
    counts: Dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _hex(match: "re.Match[str]") -> str:
    run = match.group(0)
    has_digit = any(c.isdigit() for c in run)
    has_letter = any(c.isalpha() for c in run)
    return REDACTED if has_digit and has_letter else run


def _looks_random(run: str) -> bool:
    """True for a blob of random characters, false for words joined by separators."""
    core = run.rstrip("=")
    segments = [seg for seg in re.split(r"[/_\-+]", core) if seg]
    letters = sum(len(seg) for seg in segments)
    if letters < 24:
        return False
    wordy = sum(len(seg) for seg in segments if _WORDY.fullmatch(seg))
    if wordy >= 0.6 * letters:
        return False
    body = "".join(segments)
    classes = sum((any(c.isdigit() for c in body), any(c.isupper() for c in body), any(c.islower() for c in body)))
    return classes >= 2 and _entropy(body) > 3.5


def scrub(text: str) -> str:
    """Replace anything that looks like a credential with ``[REDACTED]``.

    Deliberately aggressive. A false positive costs a slightly uglier branch
    name in the dashboard; a false negative leaks a credential.
    """
    if not text:
        return text
    out = _PRIVATE_KEY.sub(REDACTED, text)
    out = _URL_USERINFO.sub(lambda m: m.group(1) + REDACTED + "@", out)
    out = _URL_TOKEN_USERINFO.sub(lambda m: m.group(1) + REDACTED + "@", out)
    out = _QUERY_SECRET.sub(lambda m: m.group(1) + REDACTED, out)
    out = _AUTH_HEADER.sub(lambda m: m.group(1) + " " + REDACTED, out)
    out = _ASSIGNMENT.sub(
        lambda m: m.group("key") + m.group("sep") + m.group("q") + REDACTED + m.group("q"), out
    )
    for pattern in _TOKEN_PATTERNS:
        out = pattern.sub(REDACTED, out)
    out = _LONG_HEX.sub(_hex, out)
    out = _CANDIDATE.sub(lambda m: REDACTED if _looks_random(m.group(0)) else m.group(0), out)
    return out


# --- Field validators --------------------------------------------------------

_SAFE_IDENT = re.compile(r"^[A-Za-z0-9._:@\[\]/+\-]{1,120}$")
_SESSION_ID = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")
_JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,15}-\d{1,7}$")
_ISSUE_NUM = re.compile(r"^#\d{1,9}$")
_SCP_REMOTE = re.compile(r"^(?:[^@\s]+@)?(?P<host>[A-Za-z0-9.\-]+):(?P<path>[^\s]+)$")


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit]


def _identifier(value: Any) -> Optional[str]:
    """Model names, versions, vendor slugs. Anything unusual is dropped, not scrubbed."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not _SAFE_IDENT.match(value):
        return None
    if scrub(value) != value:
        return None
    return value


def _session_id(value: Any) -> Optional[str]:
    if isinstance(value, str) and _SESSION_ID.match(value):
        return value
    return None


_LOCAL_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/|~|\.)")


def _local_name(raw: str) -> Optional[str]:
    """A local path is reduced to its last segment, never the full path: it
    usually contains the developer's username (``/Users/alice``, ``C:\\Users\\alice``)."""
    name = raw.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    name = re.sub(r"\.git$", "", name)
    if not name or ":" in name:
        return None
    name = scrub(name)
    return _clip(name, 200) if REDACTED not in name else None


def normalize_repo(value: Any) -> Optional[str]:
    """Turn any git remote into ``host/owner/name``. Credentials and schemes are dropped.

    ``https://user:token@github.com/acme/api.git`` -> ``github.com/acme/api``
    ``git@github.com:acme/api.git``                -> ``github.com/acme/api``
    A local path (no remote) is reduced to its final directory name.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()[:1000]
    host = path = ""
    if _LOCAL_PATH.match(raw):
        return _local_name(raw)
    if "://" in raw:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        path = parts.path
    else:
        m = _SCP_REMOTE.match(raw)
        if m and "/" not in m.group("host"):
            host, path = m.group("host").lower(), m.group("path")
        else:
            return _local_name(raw)
    path = re.sub(r"\.git$", "", path.strip("/"))
    if not host or not path:
        return None
    result = scrub(f"{host}/{path}")
    if REDACTED in result:
        return None
    return _clip(result, 300)


def _branch(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    return _clip(scrub(value.strip()[:1000]), 200)


# The part of an issue-tracker URL path that names a ticket, and nothing after it:
# GitHub/GitLab issues and PRs, Jira browse, Linear, generic /tickets/, Azure DevOps.
_TICKET_PATH = re.compile(
    r"^/(?:[A-Za-z0-9._~\-]{1,100}/){0,5}"
    r"(?:issues|issue|pull|pulls|merge_requests|browse|tickets?|_workitems/edit|work_packages)"
    r"/[A-Za-z0-9\-]{1,40}"
)


def normalize_task_ref(value: Any) -> Optional[str]:
    """A ticket key (``ENG-123``), an issue number (``#42``) or an issue/ticket URL.

    URLs are reduced to scheme, host and the ticket part of the path. Credentials,
    query strings, fragments and any path after the ticket id are dropped, and a URL
    whose path does not look like a ticket is rejected outright.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()[:1000]
    if _JIRA_KEY.match(raw) or _ISSUE_NUM.match(raw):
        return raw
    if raw.startswith(("http://", "https://")):
        try:
            parts = urlsplit(raw)
            host = parts.hostname
        except ValueError:
            return None
        if not host:
            return None
        ticket = _TICKET_PATH.match(parts.path)
        if not ticket:
            return None
        cleaned = urlunsplit((parts.scheme, host.lower(), ticket.group(0), "", ""))
        if scrub(cleaned) != cleaned:
            return None
        return _clip(cleaned, 300)
    return None


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _uuid(value: Any) -> Optional[str]:
    return value.lower() if isinstance(value, str) and _UUID.match(value.lower()) else None


def _enum(*allowed: str) -> Callable[[Any], Optional[str]]:
    def check(value: Any) -> Optional[str]:
        return value if isinstance(value, str) and value in allowed else None

    return check


# The allowlist. Nothing outside this dict is ever transmitted.
SESSION_FIELDS: Dict[str, Callable[[Any], Optional[str]]] = {
    "external_id": _session_id,
    "agent_vendor": _identifier,
    "agent_version": _identifier,
    "agent_model": _identifier,
    "repo": normalize_repo,
    "branch": _branch,
    "task_ref": normalize_task_ref,
    "origin": _enum("human", "workflow"),
    "start_source": _enum("startup", "resume", "clear", "compact"),
    "end_reason": _identifier,
    "task_id": _uuid,  # the Flockit task this session was started for (FLOCKIT_TASK_ID)
}

EVENT_TYPES = ("session.start", "session.activity", "session.update", "session.end")


def redact_session(fields: Dict[str, Any]) -> Dict[str, str]:
    """Apply the allowlist and validators. Unknown keys and invalid values are dropped."""
    out: Dict[str, str] = {}
    for key, validator in SESSION_FIELDS.items():
        if key not in fields:
            continue
        cleaned = validator(fields[key])
        if cleaned is not None:
            out[key] = cleaned
    return out
