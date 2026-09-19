import json
import subprocess

import pytest

from flockit import config


@pytest.fixture(autouse=True)
def flockit_home(tmp_path, monkeypatch):
    """Every test gets its own ~/.flockit and ~/.claude."""
    monkeypatch.setenv("FLOCKIT_HOME", str(tmp_path / "flockit-home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("FLOCKIT_SYNC", "1")
    monkeypatch.setenv("FLOCKIT_NO_SERVICE", "1")  # never install a real launchd/systemd service from tests
    monkeypatch.delenv("FLOCKIT_TASK_REF", raising=False)
    return tmp_path / "flockit-home"


@pytest.fixture
def configured():
    config.save(config.Config(server_url="http://127.0.0.1:9", token="flk_test"))


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "work" / "api"
    repo.mkdir(parents=True)

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git("checkout", "-q", "-b", "feature/ENG-321-rate-limits")
    git("remote", "add", "origin", "https://deploy:ghp_" + "A" * 36 + "@github.com/acme/api.git")
    return repo


@pytest.fixture
def transcript(tmp_path):
    path = tmp_path / "session.jsonl"
    lines = [
        {"type": "user", "version": "2.1.3", "message": {"role": "user", "content": "SECRET PROMPT TEXT"}},
        {"type": "assistant", "version": "2.1.3", "message": {"model": "claude-opus-5", "content": "SECRET ANSWER"}},
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path
