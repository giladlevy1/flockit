"""Local redaction. Runs on the developer's machine before anything is transmitted.

This module is the security boundary of the collector. It works in two layers:

1. **Allowlist.** Only fields named in ``SESSION_FIELDS`` ever leave the machine.
   Each field has a validator that normalises the value or rejects it. Anything
   not on the list is dropped, so a new field in Claude Code's hook payload can
   never leak by accident.
2. **Scrub.** Every surviving string is passed through ``scrub()``, which
   replaces anything that looks like a credential with ``[REDACTED]``. This is
   defence in depth: the allowlisted fields should never contain secrets, but a
   branch name or a task reference is free text typed by a human.

Prompts, transcripts, file contents, command output and file paths are never
part of the payload. They are not on the allowlist, so they cannot be sent.
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

REDACTED = "[REDACTED]"

# --- Secret patterns ---------------------------------------------------------
# Ordered: the most specific patterns run first so they win over generic ones.

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)",
    re.DOTALL,
)

_TOKEN_PATTERNS = [
    # Anthropic, OpenAI and similar "sk-" style keys (sk-ant-..., sk-proj-..., sk-...)
    re.compile(r"\bsk-(?:ant-|proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{16,}"),
    # Stripe
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}"),
    re.compile(r"\bwhsec_[A-Za-z0-9]{16,}"),
    # AWS access key id and session tokens
    re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA|AIPA)[A-Z0-9]{16}\b"),
    # GitHub tokens
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    # GitLab
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{16,}"),
    # Slack
    re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]+"),
    # Google API key
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"),
    # npm, PyPI, Hugging Face, SendGrid, Twilio, DigitalOcean
    re.compile(r"\bnpm_[A-Za-z0-9]{30,}"),
    re.compile(r"\bpypi-[A-Za-z0-9_\-]{30,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
    re.compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bSK[0-9a-fA-F]{32}\b"),
    re.compile(r"\bdo[pr]_v1_[a-f0-9]{64}"),
    # Flockit's own collector tokens
    re.compile(r"\bflk_[A-Za-z0-9_\-]{16,}"),
    # JSON Web Tokens
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
]

# Authorization headers: "Bearer <token>", "Basic <b64>", "token <token>"
_AUTH_HEADER = re.compile(r"\b(Bearer|Basic|Token)\s+[A-Za-z0-9_\-\.=+/]{8,}", re.IGNORECASE)

# Credentials embedded in a URL: scheme://user:password@host
_URL_USERINFO = re.compile(r"\b([a-z][a-z0-9+\-.]*://)[^/\s:@]*:[^/\s@]*@", re.IGNORECASE)
# Token-only userinfo: https://ghp_xxx@github.com
_URL_TOKEN_USERINFO = re.compile(r"\b([a-z][a-z0-9+\-.]*://)[^/\s@]{16,}@", re.IGNORECASE)

# Sensitive query-string parameters
_QUERY_SECRET = re.compile(
    r"([?&](?:access_token|refresh_token|id_token|token|api[_-]?key|apikey|key|secret|"
    r"client_secret|password|passwd|pwd|sig|signature|auth|code|X-Amz-Signature|X-Amz-Credential)=)"
    r"[^&#\s]+",
    re.IGNORECASE,
)

# KEY=value / KEY: value where the key name says it is secret
_SECRET_NAME = (
    r"[A-Za-z0-9_\-]*(?:SECRET|PASSWORD|PASSWD|PWD|TOKEN|API[_\-]?KEY|APIKEY|ACCESS[_\-]?KEY|"
    r"PRIVATE[_\-]?KEY|CREDENTIAL|AUTH|SESSION[_\-]?KEY|DSN|CONN(?:ECTION)?[_\-]?STR(?:ING)?|"
    r"DATABASE[_\-]?URL)[A-Za-z0-9_\-]*"
)
_ASSIGNMENT = re.compile(
    r"(?P<key>\b" + _SECRET_NAME + r")(?P<sep>\s*=>\s*|\s*[=:]\s*)(?P<q>[\"']?)(?P<val>[^\s\"'&,;]+)(?P=q)",
    re.IGNORECASE,
)

# Long runs that do not match a known format. Hex runs are always redacted;
# base64-ish runs only when they look random (mixed classes, high entropy), so a
# long readable branch name such as "feature/improve-session-list-filters" survives.
_LONG_HEX = re.compile(r"\b[a-f0-9]{40,}\b", re.IGNORECASE)
_CANDIDATE = re.compile(r"[A-Za-z0-9+/_\-]{32,}={0,2}")


def _entropy(s: str) -> float:
    counts: Dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _looks_random(run: str) -> bool:
    core = run.rstrip("=")
    # Judge each path/word segment separately: a secret is one unbroken blob.
    longest = max(re.split(r"[/_\-]", core), key=len)
    if len(longest) < 32:
        return False
    has_digit = any(c.isdigit() for c in longest)
    has_upper = any(c.isupper() for c in longest)
    has_lower = any(c.islower() for c in longest)
    return has_digit and has_upper and has_lower and _entropy(longest) > 4.0


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
    out = _LONG_HEX.sub(REDACTED, out)
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


def normalize_repo(value: Any) -> Optional[str]:
    """Turn any git remote into ``host/owner/name``. Credentials and schemes are dropped.

    ``https://user:token@github.com/acme/api.git`` -> ``github.com/acme/api``
    ``git@github.com:acme/api.git``                -> ``github.com/acme/api``
    A local path (no remote) is reduced to its final directory name.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    host = path = ""
    if "://" in raw:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        path = parts.path
    else:
        m = _SCP_REMOTE.match(raw)
        if m and "/" not in m.group("host"):
            host, path = m.group("host").lower(), m.group("path")
        else:
            # A local path: keep only the last segment, never the full path
            # (it usually contains the developer's username).
            name = raw.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1]
            name = re.sub(r"\.git$", "", name)
            name = scrub(name)
            return _clip(name, 200) if name and REDACTED not in name else None
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
    return _clip(scrub(value.strip()), 200)


def normalize_task_ref(value: Any) -> Optional[str]:
    """A ticket key (``ENG-123``), an issue number (``#42``) or an issue/ticket URL.

    URLs keep scheme, host and path only: query strings and fragments are dropped,
    because that is where tokens and signatures live.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if _JIRA_KEY.match(raw) or _ISSUE_NUM.match(raw):
        return raw
    if raw.startswith(("http://", "https://")):
        parts = urlsplit(raw)
        if not parts.hostname:
            return None
        cleaned = urlunsplit((parts.scheme, parts.hostname.lower(), parts.path, "", ""))
        cleaned = scrub(cleaned)
        if REDACTED in cleaned:
            return None
        return _clip(cleaned, 300)
    return None


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
