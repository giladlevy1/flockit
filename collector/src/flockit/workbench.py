"""The workbench an AI developer works on: its database and other services.

A person's laptop has a database with realistic data in it. It survives reboots, it holds
the schema they migrated last week, and it is the reason they can say "I ran it" before
asking for a review. An agent without one can only write code that looks right.

So each AI developer can be given a workbench: a private docker network with a few
services on it, started beside the sandbox and kept between tasks. The sandbox is thrown
away after every task; the workbench is not.

    flockit-env-<id>            network, shared by every task for this workbench
    flockit-env-<id>-db         one container per service, reused
    flockit-env-<id>-db-data    its volume, where the data actually lives

The declaration comes from the server (images, ports, variable names) and is checked again
here: nothing from an API response reaches a command line unvalidated.
"""

from __future__ import annotations

import re
import subprocess
import time
from typing import Any, Dict, List, Optional

from flockit import log

NAME = re.compile(r"^[a-z][a-z0-9\-]{0,30}$")
IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,150}(?::[A-Za-z0-9._\-]{1,80})?(?:@sha256:[a-f0-9]{64})?$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,60}$")
READY_TIMEOUT = 120
START_TIMEOUT = 180


def _docker(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def _clean(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only what is well formed. A malformed service is dropped, not passed to docker."""
    services = []
    for s in spec.get("services") or []:
        if not isinstance(s, dict):
            continue
        name, image = str(s.get("name") or ""), str(s.get("image") or "")
        if not NAME.match(name) or not IMAGE.match(image):
            log.write(f"workbench: ignoring service {name!r} ({image!r})")
            continue
        env = {
            k: str(v)
            for k, v in (s.get("env") or {}).items()
            if ENV_NAME.match(str(k)) and not any(c in str(v) for c in "\r\n\x00")
        }
        data = str(s.get("data_path") or "")
        services.append(
            {
                "name": name,
                "image": image,
                "env": env,
                "url_env": str(s.get("url_env") or "") if ENV_NAME.match(str(s.get("url_env") or "")) else "",
                "url": str(s.get("url") or "")[:300],
                "ready": str(s.get("ready") or "")[:200],
                "data_path": data if data.startswith("/") and ".." not in data else "",
            }
        )
    variables = {
        k: str(v)
        for k, v in (spec.get("variables") or {}).items()
        if ENV_NAME.match(str(k)) and not any(c in str(v) for c in "\r\n\x00")
    }
    return {
        "id": re.sub(r"[^a-z0-9\-]", "", str(spec.get("id") or "")[:36]),
        "name": str(spec.get("name") or "workbench")[:80],
        "services": services,
        "variables": variables,
        "secret_names": [n for n in (spec.get("secret_names") or []) if ENV_NAME.match(str(n))],
        "setup_script": spec.get("setup_script") or "",
        "persistent": bool(spec.get("persistent", True)),
    }


class Workbench:
    """Brings one workbench up beside a sandbox, and (for throwaway ones) takes it down."""

    def __init__(self, spec: Dict[str, Any], image: str) -> None:
        self.spec = _clean(spec)
        self.image = image
        self.id = self.spec["id"] or "adhoc"
        self.prefix = f"flockit-env-{self.id[:12]}"
        self.network = self.prefix
        # Whether the one-time setup script has already succeeded for this workbench.
        # Recorded by a marker volume rather than inferred from the service volumes, so a
        # workbench with no services — or with services that keep no data — behaves the
        # same as one with a database, and a setup that *failed* is retried next time.
        self.seeded = False

    # --- naming ----------------------------------------------------------------

    def container(self, service: str) -> str:
        return f"{self.prefix}-{service}"

    def volume(self, service: str) -> str:
        return f"{self.prefix}-{service}-data"

    # --- lifecycle --------------------------------------------------------------

    def _ensure_network(self) -> None:
        if _docker("network", "inspect", self.network).returncode != 0:
            _docker("network", "create", self.network)

    def _running(self, name: str) -> Optional[str]:
        out = _docker("inspect", "-f", "{{.State.Status}}", name)
        return out.stdout.strip() if out.returncode == 0 else None

    def _start_service(self, s: Dict[str, Any]) -> None:
        name = self.container(s["name"])
        state = self._running(name)
        if state == "running":
            return
        if state is not None:
            if _docker("start", name).returncode == 0:
                return
            _docker("rm", "-f", name)
        cmd = ["run", "-d", "--name", name, "--network", self.network, "--network-alias", s["name"],
               "--restart", "unless-stopped", "--memory", "2g", "--pids-limit", "512"]
        if s["data_path"]:
            volume = self.volume(s["name"])
            if _docker("volume", "inspect", volume).returncode != 0:
                _docker("volume", "create", volume)
            cmd += ["-v", f"{volume}:{s['data_path']}"]
        for key, value in s["env"].items():
            cmd += ["-e", f"{key}={value}"]
        cmd.append(s["image"])
        out = _docker(*cmd, timeout=START_TIMEOUT)
        if out.returncode != 0:
            raise RuntimeError(f"could not start {s['name']}: {out.stderr.strip()[:300]}")

    def _wait_ready(self, s: Dict[str, Any]) -> None:
        if not s["ready"]:
            return
        name = self.container(s["name"])
        deadline = time.monotonic() + READY_TIMEOUT
        while time.monotonic() < deadline:
            if _docker("exec", name, "sh", "-c", s["ready"], timeout=30).returncode == 0:
                return
            time.sleep(2)
        raise RuntimeError(f"{s['name']} did not become ready within {READY_TIMEOUT}s")

    def marker(self) -> str:
        return f"{self.prefix}-state"

    def up(self) -> None:
        """Start everything and wait until the agent can actually use it."""
        self.seeded = _docker("volume", "inspect", self.marker()).returncode == 0
        if not self.spec["services"]:
            return
        self._ensure_network()
        for s in self.spec["services"]:
            self._start_service(s)
        for s in self.spec["services"]:
            self._wait_ready(s)

    def mark_seeded(self) -> None:
        """Called once the setup script has actually succeeded. Until then it runs again
        next time, because a half-seeded database is worse than an empty one."""
        _docker("volume", "create", self.marker())
        self.seeded = True

    def env(self) -> Dict[str, str]:
        """What the agent reads: DATABASE_URL and friends, plus the workbench's own variables."""
        out = dict(self.spec["variables"])
        for s in self.spec["services"]:
            if s["url_env"] and s["url"]:
                out[s["url_env"]] = s["url"]
        out["FLOCKIT_WORKBENCH"] = self.spec["name"]
        return out

    def docker_args(self) -> List[str]:
        return ["--network", self.network] if self.spec["services"] else []

    def setup_command(self) -> Optional[str]:
        """The one-time seed step, if this workbench has one and its data is new."""
        if self.seeded or not self.spec["setup_script"].strip():
            return None
        return self.spec["setup_script"]

    def down(self) -> None:
        """Throwaway workbenches are removed with their data; persistent ones keep running."""
        if self.spec["persistent"]:
            return
        for s in self.spec["services"]:
            _docker("rm", "-f", self.container(s["name"]))
            if s["data_path"]:
                _docker("volume", "rm", self.volume(s["name"]))
        _docker("volume", "rm", self.marker())
        if self.spec["services"]:
            _docker("network", "rm", self.network)

    # --- maintenance -------------------------------------------------------------

    @staticmethod
    def list_all() -> List[Dict[str, str]]:
        out = _docker("ps", "-a", "--filter", "name=flockit-env-", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}")
        rows = []
        for line in out.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                rows.append({"name": parts[0], "image": parts[1], "status": parts[2]})
        return rows

    @staticmethod
    def remove(env_id: str) -> int:
        """Tear one workbench down by id, data included (``flockit runner workbench rm <id>``)."""
        prefix = f"flockit-env-{env_id[:12]}"
        removed = 0
        for line in _docker("ps", "-aq", "--filter", f"name={prefix}").stdout.split():
            _docker("rm", "-f", line)
            removed += 1
        for line in _docker("volume", "ls", "-q", "--filter", f"name={prefix}").stdout.split():
            _docker("volume", "rm", line)
        _docker("network", "rm", prefix)
        return removed
