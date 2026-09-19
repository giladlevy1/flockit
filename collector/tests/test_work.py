"""The laptop agent and the AI-developer runner, end to end against a stub server and a
fake `claude` binary: workspaces, headless and interactive runs, streaming, reporting."""

import json
import os
import subprocess
import time
import uuid

import pytest

from flockit import config, launch, repos, workspace
from flockit.agent import Agent, headless_command
from flockit.runner import Runner, RunnerConfig
from tests.stub_server import StubServer

GH = "ghp_" + "1234567890abcdefghijABCDEFGHIJ123456"


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x"))


@pytest.fixture
def server():
    s = StubServer()
    yield s
    s.close()


@pytest.fixture
def origin(tmp_path):
    """A bare 'remote' with one commit on main, plus the developer's checkout of it."""
    bare = tmp_path / "remote" / "app.git"
    bare.mkdir(parents=True)
    git(bare, "init", "-q", "--bare", "-b", "main")
    checkout = tmp_path / "code" / "app"
    checkout.mkdir(parents=True)
    git(checkout, "init", "-q", "-b", "main")
    (checkout / "app.py").write_text("print('hi')\n")
    git(checkout, "add", ".")
    git(checkout, "commit", "-qm", "init")
    git(checkout, "remote", "add", "origin", str(bare))
    git(checkout, "push", "-q", "origin", "main")
    return bare, checkout


def fake_claude(tmp_path, name, body):
    path = tmp_path / "bin" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def task(**kw):
    t = {"id": str(uuid.uuid4()), "title": "Add a greeting", "prompt": "Add hello() to app.py", "repo": "app",
         "base_branch": None, "interactive": False, "permission_profile": "edit", "task_ref": None}
    t["branch"] = f"flockit/{t['id'][:8]}-add-a-greeting"
    t.update(kw)
    return t


def wait_for(predicate, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


# --- workspaces ------------------------------------------------------------------


def test_worktree_leaves_the_developers_checkout_alone(origin):
    _, checkout = origin
    (checkout / "wip.txt").write_text("uncommitted work")
    repos.remember("app", str(checkout))
    t = task()
    path = workspace.prepare("app", None, t["branch"], t["id"])
    assert os.path.isdir(path) and path != str(checkout)
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=path, capture_output=True, text=True).stdout.strip()
    assert branch == t["branch"]
    assert not os.path.exists(os.path.join(path, "wip.txt"))
    assert (checkout / "wip.txt").exists()  # untouched
    assert workspace.prepare("app", None, t["branch"], t["id"]) == path  # idempotent


def test_unknown_repo_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("FLOCKIT_WORKSPACES", str(tmp_path / "ws"))
    with pytest.raises(workspace.WorkspaceError, match="Could not find"):
        workspace.prepare("git.invalid/nobody/nothing", None, "flockit/x", str(uuid.uuid4()))


def test_headless_command_permissions():
    edit = headless_command("claude", "p", "edit")
    assert "--permission-mode" in edit and "acceptEdits" in edit and "Bash(git:*)" in edit
    assert "--dangerously-skip-permissions" not in edit
    assert "plan" in headless_command("claude", "p", "read_only")
    # a laptop never grants full access, whatever the task asks for
    assert "--dangerously-skip-permissions" not in headless_command("claude", "p", "full")


# --- laptop agent -----------------------------------------------------------------


def test_agent_runs_headless_task_and_reports(server, origin, tmp_path, monkeypatch):
    _, checkout = origin
    repos.remember("app", str(checkout))
    claude = fake_claude(tmp_path, "claude", """
echo "task=$FLOCKIT_TASK_ID" > "$PWD/ran.txt"
pwd >> "$PWD/ran.txt"
echo '{"type":"result","subtype":"success","is_error":false,"result":"Added hello(). Opened https://github.com/acme/app/pull/5","total_cost_usd":0.07}'
""")
    monkeypatch.setenv("FLOCKIT_CLAUDE_BIN", str(claude))
    config.save(config.Config(server_url=server.url, token="flk_t"))
    t = task()
    server.tasks.append(t)
    server.offers.append({"id": "o1", "title": "An offer", "repo": "app"})
    agent = Agent(config.load())
    body = agent.poll_once(wait=0)
    assert body["task"]["id"] == t["id"]
    assert wait_for(lambda: server.state.get(t["id"]) == "succeeded")
    statuses = [r[1]["status"] for r in server.reports if r[0] == t["id"]]
    assert statuses == ["running", "succeeded"]
    final = server.reports[-1][1]
    assert final["cost_usd"] == 0.07 and "hello()" in final["result"]
    worktree = next((config.home() / "worktrees").iterdir())
    ran = (worktree / "ran.txt").read_text()
    assert f"task={t['id']}" in ran  # the session is linked to its task through the environment


def test_agent_reports_failures_with_redacted_detail(server, origin, tmp_path, monkeypatch):
    _, checkout = origin
    repos.remember("app", str(checkout))
    claude = fake_claude(tmp_path, "claude", f"""
echo "fatal: could not push with {GH} from $PWD" >&2
exit 1
""")
    monkeypatch.setenv("FLOCKIT_CLAUDE_BIN", str(claude))
    config.save(config.Config(server_url=server.url, token="flk_t"))
    t = task()
    server.tasks.append(t)
    Agent(config.load()).poll_once(wait=0)
    assert wait_for(lambda: server.state.get(t["id"]) == "failed")
    error = server.reports[-1][1]["error"]
    assert GH not in error and str(config.home()) not in error and "could not push" in error


def test_agent_without_claude_fails_cleanly(server, origin, monkeypatch):
    monkeypatch.setenv("FLOCKIT_CLAUDE_BIN", "/nonexistent/claude")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    config.save(config.Config(server_url=server.url, token="flk_t", claude_path=None))
    t = task()
    server.tasks.append(t)
    Agent(config.load()).poll_once(wait=0)
    assert wait_for(lambda: server.state.get(t["id"]) == "failed")
    assert "not installed" in server.reports[-1][1]["error"]


def test_interactive_task_opens_a_terminal_with_the_task(server, origin, tmp_path, monkeypatch):
    _, checkout = origin
    repos.remember("app", str(checkout))
    marker = tmp_path / "opened.txt"
    claude = fake_claude(tmp_path, "claude", f'echo "$FLOCKIT_TASK_ID|$PWD|$1" > {marker}\n')
    monkeypatch.setenv("FLOCKIT_CLAUDE_BIN", str(claude))
    monkeypatch.setenv("FLOCKIT_TERMINAL", "sh")  # stands in for Terminal.app / gnome-terminal
    config.save(config.Config(server_url=server.url, token="flk_t"))
    t = task(interactive=True, prompt="Rename it; it's \"quoted\" & $(dangerous)")
    server.tasks.append(t)
    Agent(config.load()).poll_once(wait=0)
    assert wait_for(lambda: marker.exists() and marker.read_text().strip())
    task_id, cwd, prompt = marker.read_text().strip().split("|", 2)
    assert task_id == t["id"] and "worktrees" in cwd
    assert prompt == t["prompt"]  # passed through intact, never evaluated by the shell
    assert [r[1]["status"] for r in server.reports] == ["running"]  # the session hooks report the rest


def test_launch_script_quotes_everything(tmp_path):
    script = launch.start_script("id-1", "Title with 'quotes'", str(tmp_path / "dir with space"), "p", "/bin/echo")
    text = script.read_text()
    assert "'dir with space'" in text or "dir with space'" in text
    assert "FLOCKIT_TASK_ID=id-1" in text and oct(script.stat().st_mode & 0o777) == "0o700"


# --- runner --------------------------------------------------------------------------


STREAM = [
    {"type": "system", "subtype": "init", "session_id": "abc", "model": "claude-haiku-4-5"},
    {"type": "assistant", "uuid": "a1", "message": {"id": "m1", "model": "claude-haiku-4-5", "usage": {"input_tokens": 50, "output_tokens": 10},
                                                     "content": [{"type": "text", "text": "Adding hello() now."}]}},
    {"type": "assistant", "uuid": "a2", "message": {"id": "m2", "usage": {"input_tokens": 60, "output_tokens": 12},
                                                     "content": [{"type": "tool_use", "id": "t1", "name": "Edit",
                                                                  "input": {"file_path": "__ROOT__/app.py", "old_string": "a", "new_string": "b"}}]}},
    {"type": "user", "uuid": "u1", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "edited __ROOT__/app.py"}]}},
    {"type": "result", "subtype": "success", "is_error": False, "result": "Added hello() to app.py.", "total_cost_usd": 0.02},
]


def test_runner_local_backend_end_to_end(server, origin, tmp_path, monkeypatch):
    bare, _ = origin
    lines = "\n".join("echo " + json.dumps(json.dumps(e)).replace("__ROOT__", "$PWD") for e in STREAM)
    fake_claude(tmp_path, "claude", "echo 'def hello(): pass' >> app.py\n" + lines + "\n")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    t = task(repo="example.com/acme/app", agent={"id": "ai-1", "name": "Ada", "vendor": "claude-code", "model": "claude-haiku-4-5"},
             ingest_token="flk_task")
    server.tasks.append(t)
    runner = Runner(RunnerConfig(server_url=server.url, token="frn_x", backend="local", clone_url=f"file://{bare}"))
    runner.poll_once(wait=0)
    assert wait_for(lambda: server.state.get(t["id"]) in ("succeeded", "failed"), timeout=30)
    report = server.reports[-1][1]
    assert report["status"] == "succeeded", report
    assert "Added hello()" in report["result"] and "not pushed" in report["result"]
    types = [e["type"] for e in server.events]
    assert types[0] == "session.start" and types[-1] == "session.end" and "session.transcript" in types
    assert all(e["session"]["task_id"] == t["id"] for e in server.events)
    transcript = [m for e in server.events if e["type"] == "session.transcript" for m in e["transcript"]["messages"]]
    assert transcript[0]["kind"] == "text" and transcript[0]["role"] == "user"  # the task prompt comes first
    raw = json.dumps(server.events)
    assert str(tmp_path) not in raw and "/private/" not in raw  # sandbox paths never leave
    files = [f for e in server.events if e["type"] == "session.transcript" for f in e["transcript"]["files"]]
    assert files == [{"path": "app.py", "edits": 1}]
    usage = [e["transcript"]["usage"] for e in server.events if e["type"] == "session.transcript"]
    assert sum(u["input"] for u in usage) == 110 and sum(u["output"] for u in usage) == 22
    assert types.count("session.activity") == 1  # one agent reply, one turn


def test_runner_clone_failure_is_reported(server, tmp_path):
    t = task(repo="example.invalid/none/none", agent={"name": "Ada"}, ingest_token="flk_task")
    server.tasks.append(t)
    runner = Runner(RunnerConfig(server_url=server.url, token="frn_x", backend="local", clone_url=f"file://{tmp_path}/missing.git"))
    runner.poll_once(wait=0)
    assert wait_for(lambda: server.state.get(t["id"]) == "failed", timeout=30)
    assert "Could not clone" in server.reports[-1][1]["error"]
