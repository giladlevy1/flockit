"""HTTP delivery to the configured Flockit server. The only network code in the collector.

The collector talks to exactly one host: the server URL the developer configured.
There is no other outbound connection.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from flockit import __version__, config, outbox

BATCH_SIZE = 200
TIMEOUT_SECONDS = 2.0


@dataclass
class Result:
    ok: bool
    status: Optional[int] = None
    body: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


def request(
    cfg: config.Config, method: str, path: str, payload: Optional[Dict[str, Any]] = None, timeout: float = TIMEOUT_SECONDS
) -> Result:
    url = cfg.server_url.rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + cfg.token)
    req.add_header("User-Agent", "flockit-collector/" + __version__)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            body = json.loads(raw) if raw else None
            return Result(ok=True, status=resp.status, body=body)
    except urllib.error.HTTPError as exc:
        body = None
        try:
            body = json.loads(exc.read() or b"null")
        except ValueError:
            pass
        return Result(ok=False, status=exc.code, body=body, error=str(exc))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return Result(ok=False, error=str(exc))


def send(cfg: config.Config, events: List[Dict[str, Any]]) -> Result:
    return request(cfg, "POST", "/api/ingest/events", {"events": events})


def flush(cfg: config.Config) -> int:
    """Send everything buffered. Returns the number of events the server accepted.

    Server errors and network failures keep events for the next attempt. A 400 or
    422 means the server will never accept that batch, so it is dropped rather
    than retried forever.
    """
    events = outbox.take()
    sent = 0
    for start in range(0, len(events), BATCH_SIZE):
        batch = events[start : start + BATCH_SIZE]
        result = send(cfg, batch)
        if result.ok:
            sent += len(batch)
            continue
        if result.status in (400, 413, 422):
            continue
        outbox.restore(events[start:])
        break
    return sent
