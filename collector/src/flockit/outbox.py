"""A local, append-only buffer so a down server never loses events or blocks a session.

Every event is written here first and removed only after the server accepts it.
The lock is held for file operations only, never across a network call, so a
slow server cannot stall a second Claude Code session's hook.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List

from flockit import config

try:  # POSIX
    import fcntl

    def _lock(fh: Any) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)

    def _unlock(fh: Any) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

except ImportError:  # pragma: no cover - Windows: best effort without locking

    def _lock(fh: Any) -> None:
        return None

    def _unlock(fh: Any) -> None:
        return None


MAX_EVENTS = 10_000  # oldest events are dropped beyond this, so the file cannot grow without bound


def _path() -> Path:
    return config.outbox_path()


@contextlib.contextmanager
def _locked() -> Iterator[Any]:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+") as fh:
        _lock(fh)
        try:
            yield fh
        finally:
            _unlock(fh)


def _read(fh: Any) -> List[Dict[str, Any]]:
    fh.seek(0)
    events = []
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            continue  # a torn write from a killed process; skip it
    return events


def _write(fh: Any, events: List[Dict[str, Any]]) -> None:
    events = events[-MAX_EVENTS:]
    fh.seek(0)
    fh.truncate()
    for event in events:
        fh.write(json.dumps(event, separators=(",", ":")) + "\n")
    fh.flush()


def append(event: Dict[str, Any]) -> None:
    with _locked() as fh:
        fh.seek(0, os.SEEK_END)
        fh.write(json.dumps(event, separators=(",", ":")) + "\n")
        fh.flush()


def take() -> List[Dict[str, Any]]:
    """Remove and return every buffered event. Callers must ``restore`` what they fail to send."""
    with _locked() as fh:
        events = _read(fh)
        if events:
            _write(fh, [])
        return events


def restore(events: List[Dict[str, Any]]) -> None:
    """Put unsent events back in front of anything appended while we were sending."""
    if not events:
        return
    with _locked() as fh:
        _write(fh, events + _read(fh))


def pending() -> int:
    if not _path().exists():
        return 0
    with _locked() as fh:
        return len(_read(fh))
