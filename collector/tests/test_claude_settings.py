import json

import pytest

from flockit import claude_settings


def _settings():
    return json.loads(claude_settings.settings_path().read_text())


def test_install_into_empty_config():
    claude_settings.install()
    data = _settings()
    assert set(data["hooks"]) == set(claude_settings.EVENTS)
    assert claude_settings.installed()


def test_install_preserves_existing_settings_and_hooks():
    path = claude_settings.settings_path()
    path.parent.mkdir(parents=True)
    existing = {
        "model": "opus",
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]},
    }
    path.write_text(json.dumps(existing))
    claude_settings.install()
    data = _settings()
    assert data["model"] == "opus"
    assert data["permissions"] == existing["permissions"]
    commands = [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]]
    assert "say done" in commands and any(claude_settings.MARKER in c for c in commands)
    assert path.with_name("settings.json.flockit-backup").exists()


def test_install_is_idempotent():
    claude_settings.install()
    claude_settings.install()
    data = _settings()
    for event in claude_settings.EVENTS:
        assert len(data["hooks"][event]) == 1


def test_uninstall_removes_only_ours():
    path = claude_settings.settings_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}))
    claude_settings.install()
    claude_settings.uninstall()
    assert _settings() == {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}
    assert not claude_settings.installed()


def test_refuses_to_overwrite_unparseable_settings():
    path = claude_settings.settings_path()
    path.parent.mkdir(parents=True)
    path.write_text("{ this is not json")
    with pytest.raises(ValueError):
        claude_settings.install()
    assert path.read_text() == "{ this is not json"
