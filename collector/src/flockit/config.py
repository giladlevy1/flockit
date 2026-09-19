"""Collector configuration and local state, all under ``~/.flockit`` (or ``$FLOCKIT_HOME``)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def home() -> Path:
    override = os.environ.get("FLOCKIT_HOME")
    return Path(override).expanduser() if override else Path.home() / ".flockit"


def config_path() -> Path:
    return home() / "config.json"


def outbox_path() -> Path:
    return home() / "outbox.jsonl"


def state_dir() -> Path:
    return home() / "sessions"


def log_path() -> Path:
    return home() / "collector.log"


@dataclass
class Config:
    server_url: str
    token: str
    # Absolute path to the claude binary, recorded at install time: the background
    # agent runs under launchd/systemd with a minimal PATH.
    claude_path: Optional[str] = None

    @property
    def ingest_url(self) -> str:
        return self.server_url.rstrip("/") + "/api/ingest/events"


def load() -> Optional[Config]:
    try:
        data = json.loads(config_path().read_text())
        return Config(server_url=data["server_url"], token=data["token"], claude_path=data.get("claude_path"))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save(cfg: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"server_url": cfg.server_url, "token": cfg.token, "claude_path": cfg.claude_path}, indent=2))
    os.chmod(tmp, 0o600)  # the token is a credential
    tmp.replace(path)


def delete() -> None:
    try:
        config_path().unlink()
    except FileNotFoundError:
        pass
