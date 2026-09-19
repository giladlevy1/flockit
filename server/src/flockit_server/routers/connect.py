"""Collector distribution. The server hosts the collector itself, so developers
install it from inside the network with no access to PyPI or GitHub."""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server.db import get_db
from flockit_server.deps import require_admin
from flockit_server.models import Organization, User
from flockit_server.settings import get_settings

router = APIRouter(tags=["connect"])

_WHEEL = re.compile(r"^flockit-[0-9][A-Za-z0-9.+]*-py3-none-any\.whl$")


# What a server URL may look like before it is written into a shell script.
_SAFE_URL = re.compile(r"^https?://[A-Za-z0-9.\-]{1,253}(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~\-/]{0,200})?$")


def safe_url(value: Optional[str]) -> Optional[str]:
    """``value`` without a trailing slash if it is safe to write into a shell script, else ``None``."""
    if not value:
        return None
    url = value.strip().rstrip("/")
    return url if _SAFE_URL.match(url) else None


async def public_url(request: Request, db: AsyncSession) -> tuple[str, str]:
    """The URL developers' machines use to reach this server, and where it came from.

    1. ``FLOCKIT_PUBLIC_URL`` (``env``)
    2. the address the admin used during first-run setup, stored on the organisation (``setup``)
    3. the current request (``request``), only for deployments that have neither

    The Host header of an ordinary request is never trusted once (1) or (2) exists: it
    ends up inside ``install.sh`` and in every collector's config.
    """
    configured = get_settings().public_url
    if configured:
        url = safe_url(configured)
        if url is None:
            raise HTTPException(500, "FLOCKIT_PUBLIC_URL is not a valid http(s) URL")
        return url, "env"
    stored = (await db.execute(select(Organization.public_url).limit(1))).scalar_one_or_none()
    if stored:
        return stored, "setup"
    url = safe_url(str(request.base_url))
    if url is None:
        raise HTTPException(400, "Set FLOCKIT_PUBLIC_URL to the address developers use to reach Flockit")
    return url, "request"


@lru_cache(maxsize=4)
def _sha256(path: Path, mtime: float) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
WHEEL_SHA256="__SHA256__"
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
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$SERVER/downloads/$WHEEL" -o "$TMP/$WHEEL"
"$PY" -c 'import hashlib, sys; sys.exit(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest() != sys.argv[2])' \
  "$TMP/$WHEEL" "$WHEEL_SHA256" || { echo "Checksum mismatch for $WHEEL. Aborting." >&2; exit 1; }
"$PY" -m venv --clear "$VENV"
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --no-index "$TMP/$WHEEL"

"$VENV/bin/flockit" install --server "$SERVER" --token "$TOKEN"

if [ -d "$HOME/.local/bin" ] && [ -w "$HOME/.local/bin" ]; then
  ln -sf "$VENV/bin/flockit" "$HOME/.local/bin/flockit"
  echo "Linked the flockit command into ~/.local/bin"
else
  echo "Run $VENV/bin/flockit status to check the connection at any time."
fi
"""


@router.get("/install.sh", response_class=PlainTextResponse)
async def install_script(request: Request, db: AsyncSession = Depends(get_db)) -> PlainTextResponse:
    wheel = collector_wheel()
    if wheel is None:
        raise HTTPException(503, "The collector package is missing from this server build")
    server, _ = await public_url(request, db)
    script = (
        INSTALL_SCRIPT.replace("__SERVER__", server)
        .replace("__WHEEL__", wheel.name)
        .replace("__SHA256__", _sha256(wheel, wheel.stat().st_mtime))
    )
    # The script embeds a URL; never let a shared cache replay it to someone else.
    return PlainTextResponse(script, media_type="text/x-shellscript", headers={"Cache-Control": "no-store"})


@router.get("/downloads/{name}")
async def download(name: str) -> FileResponse:
    wheel = collector_wheel()
    if wheel is None or name != wheel.name:
        raise HTTPException(404, "Not found")
    return FileResponse(wheel, media_type="application/octet-stream", filename=wheel.name)


@router.get("/api/connect")
async def connect_info(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    server, source = await public_url(request, db)
    wheel = collector_wheel()
    return {
        "server_url": server,
        "server_url_source": source,
        "collector_available": wheel is not None,
        "collector_package": wheel.name if wheel else None,
        "install_command": f"curl -fsSL {server}/install.sh | sh -s -- <token>",
    }


class PublicUrlIn(BaseModel):
    public_url: str = Field(min_length=1, max_length=300)


@router.put("/api/connect/public-url")
async def set_public_url(
    body: PublicUrlIn, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    """Change the address written into install commands. Ignored while FLOCKIT_PUBLIC_URL is set."""
    url = safe_url(body.public_url)
    if url is None:
        raise HTTPException(422, "Use a plain http(s) URL, for example https://flockit.internal.example.com")
    org = await db.get(Organization, admin.org_id)
    assert org is not None
    org.public_url = url
    await db.commit()
    return {"server_url": url}
