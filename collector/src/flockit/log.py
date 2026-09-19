"""A tiny local log for diagnosing the collector. Never contains event contents."""

from __future__ import annotations

from datetime import datetime, timezone

from flockit import config

_MAX_BYTES = 512 * 1024


def write(message: str) -> None:
    try:
        path = config.log_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.exists() and path.stat().st_size > _MAX_BYTES:
            path.write_text("")
        with open(path, "a") as fh:
            fh.write("%s %s\n" % (datetime.now(timezone.utc).isoformat(timespec="seconds"), message))
    except OSError:
        pass
