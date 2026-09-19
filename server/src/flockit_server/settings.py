from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLOCKIT_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://flockit:flockit@localhost:5432/flockit"
    # The URL developers' collectors use to reach this server. Shown in the install command.
    # Left empty, it is derived from the incoming request.
    public_url: Optional[str] = None
    # Set true when serving over HTTPS so the login cookie is marked Secure.
    secure_cookies: bool = False
    login_ttl_hours: int = 24 * 14
    # An open session with no activity for this long is marked abandoned.
    abandon_after_hours: float = 6.0
    # A session counts as live if it reported activity within this many minutes.
    live_window_minutes: int = 15
    sweep_interval_seconds: int = 300
    web_dist: Path = Path(__file__).resolve().parent / "static"
    collector_dist: Path = Path(__file__).resolve().parent / "collector_dist"


@lru_cache
def get_settings() -> Settings:
    return Settings()
