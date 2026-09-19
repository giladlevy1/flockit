"""``flockit runner``: executes AI-developer tasks in sandboxes.

Run it on any machine in your network that has Docker (like a CI self-hosted runner).
For each task it starts a fresh container, clones the repository, runs Claude Code or
Codex headless on a new branch, streams the session into Flockit live, pushes the
branch and opens a pull request. The model and git credentials live only on the
runner (environment variables), never in Flockit.

Credentials passed into sandboxes when set on the runner:
  ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN   for Claude Code
  OPENAI_API_KEY or CODEX_API_KEY                for Codex
  GH_TOKEN or GITHUB_TOKEN                       to clone private repos, push and open PRs
"""

from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flockit import __version__, config, log, transport
from flockit.conversation import Batch, Converter
from flockit.redact import redact_session, scrub

DEFAULT_IMAGE = "flockit-sandbox:latest"
TASK_TIMEOUT = 60 * 60
SECRETS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY", "GH_TOKEN", "GITHUB_TOKEN")

SANDBOX_DOCKERFILE = """\
FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates python3 python3-pip curl jq ripgrep \\
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g @anthropic-ai/claude-code @openai/codex && npm cache clean --force
USER node
WORKDIR /work
ENV HOME=/home/node CI=1
"""

# The whole sandbox lifecycle as one script. Control lines start with FLOCKIT:: and the
# agent's own JSON stream goes to stdout; git noise goes to stderr.
TASK_SCRIPT = r"""#!/bin/bash
set -uo pipefail
cd "$FLOCKIT_WORK"
TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
URL="https://$FLOCKIT_REPO.git"
if [ -n "$TOKEN" ]; then URL="https://x-access-token:${TOKEN}@$FLOCKIT_REPO.git"; fi
git clone --quiet "$URL" repo 1>&2 || { echo "FLOCKIT::error=Could not clone $FLOCKIT_REPO (set GH_TOKEN on the runner for private repositories)"; exit 20; }
cd repo
if [ -n "${FLOCKIT_BASE:-}" ]; then git checkout --quiet "$FLOCKIT_BASE" 1>&2 || { echo "FLOCKIT::error=Base branch $FLOCKIT_BASE not found"; exit 21; }; fi
echo "FLOCKIT::base=$(git rev-parse --abbrev-ref HEAD)"
git checkout --quiet -b "$FLOCKIT_BRANCH" 1>&2
START=$(git rev-parse HEAD)
PROMPT="$(cat "$FLOCKIT_WORK/prompt.md")"
if [ "$FLOCKIT_VENDOR" = "codex" ]; then
  codex exec --json $FLOCKIT_CODEX_FLAGS ${FLOCKIT_MODEL:+-m "$FLOCKIT_MODEL"} "$PROMPT"
else
  claude -p "$PROMPT" --output-format stream-json --verbose $FLOCKIT_CLAUDE_FLAGS ${FLOCKIT_MODEL:+--model "$FLOCKIT_MODEL"}
fi
CODE=$?
git add -A 1>&2
git diff --cached --quiet || git commit --quiet -m "$FLOCKIT_TITLE" -m "Flockit task $FLOCKIT_TASK_ID" 1>&2
COMMITS=$(git rev-list --count "$START"..HEAD)
echo "FLOCKIT::commits=$COMMITS"
if [ "$COMMITS" -gt 0 ] && [ -n "$TOKEN" ]; then
  git push --quiet -u origin "$FLOCKIT_BRANCH" 1>&2 && echo "FLOCKIT::pushed"
fi
exit $CODE
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunnerConfig:
    server_url: str
    token: str
    backend: str = "docker"  # docker | local
    image: str = DEFAULT_IMAGE
    capacity: int = 1
    name: str = ""
    allow_full_local: bool = False


class CodexConverter:
    """Codex ``exec --json`` events -> the same message shape Claude transcripts produce."""

    def __init__(self) -> None:
        self.seq = 0

    def feed(self, entries: List[Dict[str, Any]], batch: Batch) -> Batch:
        for e in entries:
            etype = e.get("type")
            if etype == "turn.completed" and isinstance(e.get("usage"), dict):
                u = e["usage"]
                batch.usage["input"] += int(u.get("input_tokens") or 0)
                batch.usage["cache_read"] += int(u.get("cached_input_tokens") or 0)
                batch.usage["output"] += int(u.get("output_tokens") or 0)
            if etype != "item.completed" or not isinstance(e.get("item"), dict):
                continue
            item = e["item"]
            iid = str(item.get("id") or uuid.uuid4())
            kind = item.get("type") or item.get("item_type")
            if kind in ("agent_message", "assistant_message"):
                self._add(batch, iid, "assistant", "text", scrub(str(item.get("text", "")))[:20000])
                batch.result = {"result": item.get("text", "")}
            elif kind == "command_execution":
                self._add(batch, iid + ":c", "assistant", "tool_use", scrub(str(item.get("command", "")))[:4000], "shell")
                self._add(batch, iid + ":r", "user", "tool_result", scrub(str(item.get("aggregated_output", "")))[:4000], "shell")
            elif kind == "file_change":
                for change in item.get("changes") or []:
                    path = str(change.get("path", ""))
                    if path:
                        batch.files[path] = batch.files.get(path, 0) + 1
                self._add(batch, iid, "assistant", "tool_use", ", ".join(batch.files)[:4000], "apply_patch")
        return batch

    def _add(self, batch: Batch, eid: str, role: str, kind: str, content: str, tool: Optional[str] = None) -> None:
        if content.strip():
            batch.messages.append({"id": eid[:64], "seq": self.seq, "role": role, "kind": kind, "tool_name": tool, "content": content, "at": _now()})
            self.seq += 1


class TaskRun:
    """One task in one sandbox: start, stream, finish, report."""

    def __init__(self, runner: "Runner", task: Dict[str, Any]) -> None:
        self.runner = runner
        self.task = task
        self.id = task["id"]
        self.agent = task.get("agent") or {}
        self.vendor = self.agent.get("vendor") or "claude-code"
        self.ingest = config.Config(server_url=runner.cfg.server_url, token=task["ingest_token"])
        self.external_id = self.id
        self.converter = Converter(None) if self.vendor != "codex" else CodexConverter()
        self.batch = Batch()
        self.pending: List[Dict[str, Any]] = []
        self.control: Dict[str, str] = {}
        self.proc: Optional[subprocess.Popen] = None
        self.container = f"flockit-{self.id[:12]}"

    # --- events to Flockit ------------------------------------------------

    def _fields(self, **extra: Any) -> Dict[str, Any]:
        base = {
            "external_id": self.external_id,
            "agent_vendor": self.vendor,
            "agent_model": self.batch.model or self.agent.get("model"),
            "agent_version": self.batch.version,
            "repo": self.task.get("repo"),
            "branch": self.task.get("branch"),
            "task_ref": self.task.get("task_ref"),
            "task_id": self.id,
            "origin": "workflow",
        }
        base.update(extra)
        return redact_session(base)

    def _event(self, kind: str, transcript: Optional[Dict[str, Any]] = None, **extra: Any) -> Dict[str, Any]:
        event = {"event_id": str(uuid.uuid4()), "type": kind, "occurred_at": _now(), "collector_version": __version__,
                 "session": self._fields(**extra)}
        if transcript is not None:
            event["transcript"] = transcript
        return event

    def send(self, events: List[Dict[str, Any]]) -> None:
        self.pending.extend(events)
        result = transport.send(self.ingest, self.pending[:200])
        if result.ok or (result.status in (400, 413, 422)):
            self.pending = self.pending[200:]

    def flush_batch(self, final: bool = False) -> None:
        if self.batch.messages or any(self.batch.usage.values()) or self.batch.files or final:
            payload = self.batch.payload()
            self.batch.messages, self.batch.files = [], {}
            self.batch.usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
            self.send([self._event("session.transcript", payload), self._event("session.activity")])

    # --- sandbox ----------------------------------------------------------

    def _prepare(self, workdir: str) -> Dict[str, str]:
        with open(os.path.join(workdir, "prompt.md"), "w") as fh:
            fh.write(self.task["prompt"])
        with open(os.path.join(workdir, "task.sh"), "w") as fh:
            fh.write(TASK_SCRIPT)
        os.chmod(workdir, 0o777)  # the sandbox runs as an unprivileged user
        profile = self.task.get("permission_profile", "edit")
        sandboxed = self.runner.cfg.backend == "docker"
        full = sandboxed or (self.runner.cfg.allow_full_local and profile == "full")
        if profile == "read_only":
            claude_flags = "--permission-mode plan"
            codex_flags = "--sandbox read-only"
        elif full:
            claude_flags = "--dangerously-skip-permissions"
            codex_flags = "--dangerously-bypass-approvals-and-sandbox"
        else:
            from flockit.agent import ALLOWED_TOOLS

            claude_flags = "--permission-mode acceptEdits --allowedTools " + " ".join(shlex.quote(t) for t in ALLOWED_TOOLS)
            codex_flags = "--full-auto"
        name = self.agent.get("name") or "Flockit AI developer"
        email = f"{self.agent.get('id', 'ai')}@agents.flockit.local"
        return {
            "FLOCKIT_TASK_ID": self.id,
            "FLOCKIT_REPO": self.task.get("repo") or "",
            "FLOCKIT_BASE": self.task.get("base_branch") or "",
            "FLOCKIT_BRANCH": self.task["branch"],
            "FLOCKIT_TITLE": self.task["title"],
            "FLOCKIT_VENDOR": self.vendor,
            "FLOCKIT_MODEL": self.agent.get("model") or "",
            "FLOCKIT_CLAUDE_FLAGS": claude_flags,
            "FLOCKIT_CODEX_FLAGS": codex_flags,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }

    def _command(self, workdir: str, env: Dict[str, str]) -> tuple[List[str], Dict[str, str]]:
        if self.runner.cfg.backend == "local":
            # The runner reports this session itself, so the host's own collector hook stays quiet.
            full_env = dict(os.environ, **env, FLOCKIT_WORK=workdir, FLOCKIT_DISABLE_HOOK="1")
            return ["bash", os.path.join(workdir, "task.sh")], full_env
        cmd = ["docker", "run", "--rm", "--name", self.container, "-v", f"{workdir}:/work", "-e", "FLOCKIT_WORK=/work",
               "--memory", "4g", "--cpus", "2", "--pids-limit", "512"]
        for key, value in env.items():
            cmd += ["-e", f"{key}={value}"]
        for key in SECRETS:
            if os.environ.get(key):
                cmd += ["-e", key]  # value inherited from the runner's environment, never on the command line
        cmd += [self.runner.cfg.image, "bash", "/work/task.sh"]
        return cmd, dict(os.environ)

    def _kill(self) -> None:
        if self.runner.cfg.backend == "docker":
            subprocess.run(["docker", "kill", self.container], capture_output=True, check=False)
        elif self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)

    def execute(self) -> None:
        workdir = tempfile.mkdtemp(prefix="flockit-task-")
        status, result, error, pr_url, cost = "failed", None, None, None, None
        try:
            env = self._prepare(workdir)
            cmd, proc_env = self._command(workdir, env)
            self.runner.report(self.id, "running")
            self.send([self._event("session.start", start_source="startup")])
            self.proc = subprocess.Popen(cmd, env=proc_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
            stderr_tail: List[str] = []

            def drain_stderr() -> None:
                for err_line in self.proc.stderr:  # type: ignore[union-attr]
                    stderr_tail.append(err_line)
                    del stderr_tail[:-40]

            threading.Thread(target=drain_stderr, daemon=True).start()
            started = last_flush = last_check = time.monotonic()
            cancelled = False
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                line = line.strip()
                if line.startswith("FLOCKIT::"):
                    key, _, value = line[9:].partition("=")
                    self.control[key] = value
                elif line.startswith("{"):
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        entry = None
                    if isinstance(entry, dict):
                        if entry.get("type") == "system" and isinstance(entry.get("model"), str):
                            self.batch.model = entry["model"]
                        self.converter.feed([entry], self.batch)
                now = time.monotonic()
                if now - last_flush > 3:
                    self.flush_batch()
                    last_flush = now
                if now - last_check > 15:
                    last_check = now
                    if self.runner.cancelled(self.id):
                        cancelled = True
                        self._kill()
                        break
                if now - started > TASK_TIMEOUT:
                    self._kill()
                    error = "Timed out after 60 minutes"
                    break
            code = self.proc.wait(timeout=60)
            outcome = self.batch.result or {}
            self.flush_batch()
            summary = outcome.get("result") if isinstance(outcome, dict) else None
            cost = outcome.get("total_cost_usd") if isinstance(outcome, dict) else None
            if cancelled:
                self.send([self._event("session.end", end_reason="cancelled")])
                return
            if self.control.get("error"):
                error = self.control["error"]
            elif code == 0 and not (isinstance(outcome, dict) and outcome.get("is_error")):
                status, result = "succeeded", summary or "Done."
                if "pushed" in self.control:
                    pr_url = self.runner.open_pr(self.task, self.control.get("base"), summary or "")
                    if not pr_url:
                        result += f"\n\nPushed branch `{self.task['branch']}`."
                elif self.control.get("commits", "0") != "0":
                    result += "\n\nChanges were committed in the sandbox but not pushed: set GH_TOKEN on the runner."
                else:
                    result += "\n\nNo code changes."
            else:
                error = error or summary or "".join(stderr_tail)[-3000:] or f"The agent exited with code {code}"
            self.send([self._event("session.end", end_reason="completed" if status == "succeeded" else "error")])
        except Exception as exc:  # noqa: BLE001
            error = f"The runner failed to run this task: {type(exc).__name__}: {exc}"
            log.write(error)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            if error or status == "succeeded":
                self.runner.report(self.id, status, result=scrub(result) if result else None,
                                   error=scrub(error) if error else None, pr_url=pr_url, cost_usd=cost)


class Runner:
    def __init__(self, cfg: RunnerConfig) -> None:
        self.cfg = cfg
        self.auth = config.Config(server_url=cfg.server_url, token=cfg.token)
        self.active: Dict[str, threading.Thread] = {}
        self.lock = threading.Lock()

    def hello(self) -> Dict[str, Any]:
        return {
            "name": self.cfg.name or socket.gethostname().split(".")[0],
            "platform": f"{platform.system().lower()}-{platform.machine()}",
            "version": __version__,
            "capabilities": {
                "backend": self.cfg.backend,
                "docker": bool(shutil.which("docker")),
                "claude": any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")) or self.cfg.backend == "local",
                "codex": any(os.environ.get(k) for k in ("OPENAI_API_KEY", "CODEX_API_KEY")),
                "git_push": any(os.environ.get(k) for k in ("GH_TOKEN", "GITHUB_TOKEN")),
            },
            "capacity": self.cfg.capacity,
        }

    def report(self, task_id: str, status: str, **fields: Any) -> None:
        payload = {"status": status, **{k: v for k, v in fields.items() if v is not None}}
        for attempt in range(5):
            r = transport.request(self.auth, "POST", f"/api/runner/tasks/{task_id}/status", payload, timeout=15)
            if r.ok or (r.status and 400 <= r.status < 500):
                return
            time.sleep(2 * (attempt + 1))

    def cancelled(self, task_id: str) -> bool:
        r = transport.request(self.auth, "GET", f"/api/runner/tasks/{task_id}", timeout=10)
        return bool(r.ok and (r.body or {}).get("status") == "cancelled")

    def open_pr(self, task: Dict[str, Any], base: Optional[str], summary: str) -> Optional[str]:
        """Open a pull request on GitHub for the pushed branch. Only the runner talks to GitHub."""
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        repo = task.get("repo") or ""
        host, _, path = repo.partition("/")
        if not token or not path:
            return None
        api = "https://api.github.com" if host == "github.com" else f"https://{host}/api/v3"
        agent = (task.get("agent") or {}).get("name", "An AI developer")
        body = (
            f"{summary.strip()}\n\n---\nOpened by **{agent}** through Flockit for task *{task['title']}*"
            + (f" ({task['task_ref']})" if task.get("task_ref") else "")
        )
        data = json.dumps({"title": task["title"], "head": task["branch"], "base": task.get("base_branch") or base or "main",
                           "body": scrub(body)[:60000], "draft": False}).encode()
        req = urllib.request.Request(f"{api}/repos/{path}/pulls", data=data, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "flockit-runner/" + __version__)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read()).get("html_url")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.write(f"could not open PR: {exc}")
            return None

    def poll_once(self, wait: int = 25) -> Optional[Dict[str, Any]]:
        r = transport.request(self.auth, "POST", f"/api/runner/poll?wait={wait}", self.hello(), timeout=wait + 15)
        if not r.ok:
            if r.status == 401:
                raise SystemExit("The server rejected the runner token. Create a new runner in Flockit (AI developers → Runners).")
            return None
        task = (r.body or {}).get("task")
        if task:
            run = TaskRun(self, task)
            thread = threading.Thread(target=self._run, args=(run,), daemon=True)
            with self.lock:
                self.active[task["id"]] = thread
            thread.start()
        return r.body

    def _run(self, run: TaskRun) -> None:
        try:
            run.execute()
        finally:
            with self.lock:
                self.active.pop(run.id, None)

    def run_forever(self) -> None:
        print(f"flockit runner {__version__}: {self.cfg.backend} backend, capacity {self.cfg.capacity}, server {self.cfg.server_url}")
        backoff = 2
        while True:
            with self.lock:
                busy = len(self.active) >= self.cfg.capacity
            if busy:
                time.sleep(3)
                continue
            body = self.poll_once()
            if body is None:
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
            else:
                backoff = 2


def build_image(image: str = DEFAULT_IMAGE) -> int:
    with tempfile.TemporaryDirectory() as ctx:
        with open(os.path.join(ctx, "Dockerfile"), "w") as fh:
            fh.write(SANDBOX_DOCKERFILE)
        return subprocess.call(["docker", "build", "-t", image, ctx])
