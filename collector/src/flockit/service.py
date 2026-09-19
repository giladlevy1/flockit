"""Install ``flockit agent`` as a per-user background service (launchd on macOS,
systemd --user on Linux). Nothing runs as root; nothing is installed system-wide."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

from flockit import config

LABEL = "dev.flockit.agent"


def _disabled() -> bool:
    return os.environ.get("FLOCKIT_NO_SERVICE") == "1"


def _env() -> dict:
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}
    for key in ("FLOCKIT_HOME", "CLAUDE_CONFIG_DIR", "FLOCKIT_WORKSPACES", "FLOCKIT_TERMINAL", "FLOCKIT_TERMINAL_APP"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "flockit-agent.service"


def _plist() -> str:
    log = escape(str(config.home() / "agent.log"))
    env = "".join(f"<key>{escape(k)}</key><string>{escape(v)}</string>" for k, v in _env().items())
    args = "".join(f"<string>{escape(a)}</string>" for a in (sys.executable, "-m", "flockit", "agent", "run"))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{LABEL}</string>
<key>ProgramArguments</key><array>{args}</array>
<key>EnvironmentVariables</key><dict>{env}</dict>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>10</integer>
<key>ProcessType</key><string>Background</string>
<key>StandardOutPath</key><string>{log}</string>
<key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
"""


def _unit() -> str:
    env = "\n".join(f'Environment="{k}={v}"' for k, v in _env().items())
    return f"""[Unit]
Description=Flockit agent: starts Flockit tasks on this machine
After=network-online.target

[Service]
ExecStart={sys.executable} -m flockit agent run
Restart=always
RestartSec=10
{env}

[Install]
WantedBy=default.target
"""


def install() -> Optional[str]:
    """Install and start the service. Returns a short description, or None if unsupported."""
    if _disabled():
        return None
    if sys.platform == "darwin":
        path = _plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        uninstall()
        path.write_text(_plist())
        subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], capture_output=True, check=False)
        return f"launchd agent {LABEL}"
    if sys.platform.startswith("linux") and shutil.which("systemctl"):
        path = _unit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_unit())
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, check=False)
        out = subprocess.run(["systemctl", "--user", "enable", "--now", "flockit-agent.service"], capture_output=True, check=False)
        return "systemd user service flockit-agent" if out.returncode == 0 else None
    return None


def uninstall() -> None:
    if _disabled():
        return
    if sys.platform == "darwin":
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, check=False)
        try:
            _plist_path().unlink()
        except FileNotFoundError:
            pass
    elif sys.platform.startswith("linux") and shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "disable", "--now", "flockit-agent.service"], capture_output=True, check=False)
        try:
            _unit_path().unlink()
        except FileNotFoundError:
            pass


def status() -> str:
    if sys.platform == "darwin":
        out = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, text=True, check=False)
        if out.returncode != 0:
            return "not installed"
        return "running" if "state = running" in out.stdout else "installed, not running"
    if shutil.which("systemctl"):
        out = subprocess.run(["systemctl", "--user", "is-active", "flockit-agent.service"], capture_output=True, text=True, check=False)
        return out.stdout.strip() or "not installed"
    return "unsupported on this platform (run `flockit agent run` yourself)"
