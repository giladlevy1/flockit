"""Read the model and Claude Code version from the tail of a session transcript.

Only two identifier fields are read. Message content is never parsed or kept.
"""

from __future__ import annotations

import json
import os
from typing import Optional, Tuple

_TAIL_BYTES = 256 * 1024


def model_and_version(path: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not path:
        return None, None
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > _TAIL_BYTES:
                fh.seek(size - _TAIL_BYTES)
                fh.readline()  # drop the partial first line
            lines = fh.read().splitlines()
    except OSError:
        return None, None

    model = version = None
    for raw in reversed(lines):
        if model and version:
            break
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        if version is None and isinstance(entry.get("version"), str):
            version = entry["version"]
        if model is None and entry.get("type") == "assistant":
            message = entry.get("message")
            if isinstance(message, dict) and isinstance(message.get("model"), str):
                candidate = message["model"]
                if candidate and not candidate.startswith("<"):  # "<synthetic>" entries
                    model = candidate
    return model, version
