"""Collector distribution. The server hosts the collector itself, so developers
install it from inside the network with no access to PyPI or GitHub."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

from flockit_server.settings import get_settings

router = APIRouter(tags=["connect"])

_WHEEL = re.compile(r"^flockit-[0-9][A-Za-z0-9.+]*-py3-none-any\.whl$")


def public_url(request: Request) -> str:
    configured = get_settings().public_url
    return (configured or str(request.base_url)).rstrip("/")


def collector_wheel() -> Optional[Path]:
    dist = get_settings().collector_dist
    if not dist.is_dir():
        return None
    wheels = sorted(p for p in dist.iterdir() if _WHEEL.match(p.name))
    return wheels[-1] if wheels else None


INSTALL_SCRIPT = r"""#!/bin/sh
# Flockit collector installer, served by your Flockit server at __SERVER__.
# Installs into ~/.flockit/venv from this server only: no PyPI, no GitHub, no telemetry.
set -eu

SERVER="__SERVER__"
WHEEL="__WHEEL__"
TOKEN="${1:-${FLOCKIT_TOKEN:-}}"

if [ -z "$TOKEN" ]; then
  echo "usage: curl -fsSL $SERVER/install.sh | sh -s -- <collector-token>" >&2
  echo "Create a token on the Connect page: $SERVER/connect" >&2
  exit 2
fi

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Flockit needs Python 3.9 or newer (python3 not found)." >&2
  exit 1
fi

HOME_DIR="${FLOCKIT_HOME:-$HOME/.flockit}"
VENV="$HOME_DIR/venv"
mkdir -p "$HOME_DIR"
chmod 700 "$HOME_DIR"

echo "Installing the Flockit collector into $VENV"
"$PY" -m venv --clear "$VENV"
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --no-index "$SERVER/downloads/$WHEEL"

"$VENV/bin/flockit" install --server "$SERVER" --token "$TOKEN"

if [ -d "$HOME/.local/bin" ] && [ -w "$HOME/.local/bin" ]; then
  ln -sf "$VENV/bin/flockit" "$HOME/.local/bin/flockit"
  echo "Linked the flockit command into ~/.local/bin"
else
  echo "Run $VENV/bin/flockit status to check the connection at any time."
fi
"""


@router.get("/install.sh", response_class=PlainTextResponse)
async def install_script(request: Request) -> PlainTextResponse:
    wheel = collector_wheel()
    if wheel is None:
        raise HTTPException(503, "The collector package is missing from this server build")
    script = INSTALL_SCRIPT.replace("__SERVER__", public_url(request)).replace("__WHEEL__", wheel.name)
    return PlainTextResponse(script, media_type="text/x-shellscript")


@router.get("/downloads/{name}")
async def download(name: str) -> FileResponse:
    wheel = collector_wheel()
    if wheel is None or name != wheel.name:
        raise HTTPException(404, "Not found")
    return FileResponse(wheel, media_type="application/octet-stream", filename=wheel.name)


@router.get("/api/connect")
async def connect_info(request: Request) -> dict:
    server = public_url(request)
    wheel = collector_wheel()
    return {
        "server_url": server,
        "collector_available": wheel is not None,
        "collector_package": wheel.name if wheel else None,
        "install_command": f"curl -fsSL {server}/install.sh | sh -s -- <token>",
    }
