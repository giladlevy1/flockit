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
    # How often to check for sessions whose machine went away mid-work. Short on purpose:
    # this is the delay between closing a laptop and the work being picked up.
    continuity_interval_seconds: int = 30
    # Git hosts tasks may point at. Runners send git credentials only to these hosts,
    # so a task can never make a runner hand its token to someone else's server.
    allowed_git_hosts: str = "github.com,gitlab.com,bitbucket.org"
    # Webhook deliveries accepted per workflow per hour (a leaked URL cannot run up a bill).
    webhook_rate_per_hour: int = 120
    # Slack: the app's signing secret, so slash commands and events can be verified.
    # Deployment config, never stored in the database. Empty disables the Slack endpoints.
    slack_signing_secret: str = ""
    web_dist: Path = Path(__file__).resolve().parent / "static"
    collector_dist: Path = Path(__file__).resolve().parent / "collector_dist"


@lru_cache
def get_settings() -> Settings:
    return Settings()
