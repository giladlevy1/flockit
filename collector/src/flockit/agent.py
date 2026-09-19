"""``flockit agent``: the background service that starts Flockit tasks on this laptop.

It long-polls the server. New offers become desktop notifications. A task the
developer accepted opens as an interactive Claude Code session in a terminal; a task
the developer allowed to auto-start runs headless and reports its result. Either way
the work happens in a fresh git worktree on the task's branch.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

from flockit import __version__, config, launch, log, transport, workspace
from flockit.conversation import PathRewriter
from flockit.redact import scrub

POLL_WAIT = 25
HEADLESS_TIMEOUT = 2 * 60 * 60
MAX_PARALLEL = 2

# Commands a headless task may run without asking. Anything else is denied, because
# nobody is at the keyboard to approve it.
ALLOWED_TOOLS = [
    "Read", "Edit", "Write", "MultiEdit", "Glob", "Grep", "LS", "TodoWrite", "NotebookEdit",
    "Bash(git:*)", "Bash(gh:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(npm:*)", "Bash(npx:*)", "Bash(pnpm:*)",
    "Bash(yarn:*)", "Bash(node:*)", "Bash(python:*)", "Bash(python3:*)", "Bash(pytest:*)", "Bash(uv:*)",
    "Bash(go:*)", "Bash(cargo:*)", "Bash(make:*)", "Bash(mvn:*)", "Bash(gradle:*)", "Bash(./gradlew:*)",
]


def machine_name() -> str:
    return os.environ.get("FLOCKIT_MACHINE_NAME") or socket.gethostname().split(".")[0] or "laptop"


def claude_binary(cfg: config.Config) -> Optional[str]:
    for candidate in (os.environ.get("FLOCKIT_CLAUDE_BIN"), cfg.claude_path, shutil.which("claude")):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def headless_command(claude: str, prompt: str, profile: str) -> List[str]:
    cmd = [claude, "-p", prompt, "--output-format", "json"]
    if profile == "read_only":
        cmd += ["--permission-mode", "plan"]
    else:
        cmd += ["--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED_TOOLS]
    return cmd


def _clean_error(text: str, workdir: Optional[str] = None) -> str:
    return scrub(PathRewriter(workdir)(text))[-4000:]


class Agent:
    def __init__(self, cfg: config.Config) -> None:
        self.cfg = cfg
        self.running: Dict[str, threading.Thread] = {}
        self.lock = threading.Lock()

    # --- server calls ----------------------------------------------------

    def hello(self) -> Dict[str, Any]:
        claude = claude_binary(self.cfg)
        return {
            "name": machine_name(),
            "platform": f"{platform.system().lower()}-{platform.machine()}",
            "version": __version__,
            "capabilities": {"claude": bool(claude), "terminal": launch.can_open_terminal()},
            "capacity": MAX_PARALLEL,
        }

    def report(self, task_id: str, status: str, **fields: Any) -> None:
        payload = {"status": status, **{k: v for k, v in fields.items() if v is not None}}
        for attempt in range(5):
            result = transport.request(self.cfg, "POST", f"/api/agent/tasks/{task_id}/status", payload, timeout=10)
            if result.ok or (result.status and 400 <= result.status < 500):
                return
            time.sleep(2 * (attempt + 1))
        log.write(f"could not report task {task_id[:8]} {status}")

    def cancelled(self, task_id: str) -> bool:
        result = transport.request(self.cfg, "GET", f"/api/agent/tasks/{task_id}/state", timeout=10)
        return bool(result.ok and (result.body or {}).get("status") in ("cancelled", "failed", "succeeded"))

    # --- running tasks ----------------------------------------------------

    def run_task(self, task: Dict[str, Any]) -> None:
        task_id = task["id"]
        workdir = None
        try:
            claude = claude_binary(self.cfg)
            if not claude:
                raise workspace.WorkspaceError("Claude Code is not installed on this machine (claude not found)")
            workdir = workspace.prepare(task.get("repo"), task.get("base_branch"), task["branch"], task_id)
            if task.get("interactive"):
                script = launch.start_script(task_id, task["title"], workdir, task["prompt"], claude)
                if launch.open_terminal(script):
                    self.report(task_id, "running")
                    launch.notify("Flockit task started", task["title"])
                    return  # the session's hooks report progress; the developer finishes it
                log.write("no terminal available; running headless instead")
            self.run_headless(task, claude, workdir)
        except workspace.WorkspaceError as exc:
            self.report(task_id, "failed", error=_clean_error(str(exc), workdir))
            launch.notify("Flockit task could not start", task["title"])
        except Exception as exc:  # noqa: BLE001
            log.write(f"task {task_id[:8]} crashed: {type(exc).__name__}")
            self.report(task_id, "failed", error=f"The agent crashed: {type(exc).__name__}")
        finally:
            with self.lock:
                self.running.pop(task_id, None)

    def run_headless(self, task: Dict[str, Any], claude: str, workdir: str) -> None:
        task_id = task["id"]
        env = dict(os.environ, FLOCKIT_TASK_ID=task_id)
        cmd = headless_command(claude, task["prompt"], task.get("permission_profile", "edit"))
        self.report(task_id, "running")
        proc = subprocess.Popen(cmd, cwd=workdir, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        box: Dict[str, str] = {}

        def collect() -> None:
            box["out"], box["err"] = proc.communicate()  # drains both pipes, so neither can fill up and block

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        started = last_check = time.monotonic()
        while reader.is_alive():
            reader.join(timeout=2)
            now = time.monotonic()
            if now - started > HEADLESS_TIMEOUT:
                proc.kill()
                self.report(task_id, "failed", error="Timed out after 2 hours")
                return
            if now - last_check > 30:
                last_check = now
                if self.cancelled(task_id):
                    proc.terminate()
                    return
        text, stderr = box.get("out", ""), box.get("err", "")
        try:
            result = json.loads(text.strip().splitlines()[-1]) if text.strip() else {}
        except ValueError:
            result = {}
        summary = result.get("result") if isinstance(result, dict) else None
        cost = result.get("total_cost_usd") if isinstance(result, dict) else None
        if proc.returncode == 0 and isinstance(result, dict) and not result.get("is_error"):
            self.report(task_id, "succeeded", result=_clean_error(summary or "Done.", workdir), cost_usd=cost)
            launch.notify("Flockit task finished", task["title"])
        else:
            detail = summary or stderr or text or f"claude exited with code {proc.returncode}"
            self.report(task_id, "failed", error=_clean_error(detail, workdir), cost_usd=cost)
            launch.notify("Flockit task failed", task["title"])

    # --- main loop --------------------------------------------------------

    def poll_once(self, wait: int = POLL_WAIT) -> Optional[Dict[str, Any]]:
        result = transport.request(self.cfg, "POST", f"/api/agent/poll?wait={wait}", self.hello(), timeout=wait + 15)
        if not result.ok:
            return None
        body = result.body or {}
        for offer in body.get("offers") or []:
            launch.notify("New task from Flockit", f"{offer.get('title')} — open Flockit to accept")
        task = body.get("task")
        if task:
            with self.lock:
                thread = threading.Thread(target=self.run_task, args=(task,), daemon=True)
                self.running[task["id"]] = thread
            thread.start()
        return body

    def run_forever(self) -> None:
        log.write(f"agent started on {machine_name()}")
        backoff = 2
        while True:
            with self.lock:
                busy = len(self.running) >= MAX_PARALLEL
            if busy:
                time.sleep(5)
                continue
            body = self.poll_once()
            if body is None:
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
            else:
                backoff = 2
