import json

from flockit import hook, outbox


def _run(**data):
    hook.run(json.dumps(data))


def _events():
    events = outbox.snapshot()
    outbox.remove(e["event_id"] for e in events)
    return events


def test_unconfigured_collector_does_nothing(git_repo):
    _run(session_id="s1", hook_event_name="SessionStart", cwd=str(git_repo), source="startup")
    assert _events() == []


def test_full_session_lifecycle(configured, git_repo, transcript):
    common = dict(session_id="s1", cwd=str(git_repo), transcript_path=str(transcript))
    _run(hook_event_name="SessionStart", source="startup", **common)
    _run(hook_event_name="UserPromptSubmit", prompt="fix it", **common)
    _run(hook_event_name="Stop", **common)
    _run(hook_event_name="SessionEnd", reason="prompt_input_exit", **common)

    events = _events()
    assert [e["type"] for e in events] == ["session.start", "session.activity", "session.end"]
    start = events[0]["session"]
    assert start == {
        "external_id": "s1",
        "agent_vendor": "claude-code",
        "agent_model": "claude-opus-5",
        "agent_version": "2.1.3",
        "origin": "human",
        "repo": "github.com/acme/api",
        "branch": "feature/ENG-321-rate-limits",
        "task_ref": "ENG-321",
        "start_source": "startup",
    }
    assert events[-1]["session"]["end_reason"] == "prompt_input_exit"
    assert len({e["event_id"] for e in events}) == 3


def test_nothing_sensitive_is_ever_buffered(configured, git_repo, transcript):
    common = dict(session_id="s2", cwd=str(git_repo), transcript_path=str(transcript))
    _run(hook_event_name="SessionStart", source="startup", **common)
    _run(hook_event_name="UserPromptSubmit", prompt="deploy with AKIA" + "IOSFODNN7EXAMPLE", **common)
    _run(hook_event_name="Stop", **common)
    raw = json.dumps(_events())
    for forbidden in ("SECRET PROMPT", "SECRET ANSWER", "AKIA", "ghp_", "deploy:", str(git_repo), "session.jsonl"):
        assert forbidden not in raw


def test_task_ref_from_prompt_sent_once(configured, tmp_path, transcript):
    plain = tmp_path / "plain"
    plain.mkdir()
    common = dict(session_id="s3", cwd=str(plain), transcript_path=str(transcript))
    _run(hook_event_name="SessionStart", source="startup", **common)
    _run(hook_event_name="UserPromptSubmit", prompt="work on https://github.com/acme/api/issues/7 please", **common)
    _run(hook_event_name="UserPromptSubmit", prompt="also PAY-9", **common)
    events = _events()
    updates = [e for e in events if e["type"] == "session.update"]
    assert len(updates) == 1
    assert updates[0]["session"]["task_ref"] == "https://github.com/acme/api/issues/7"


def test_session_started_before_install_still_reports(configured, git_repo, transcript):
    _run(session_id="s4", hook_event_name="Stop", cwd=str(git_repo), transcript_path=str(transcript))
    (event,) = _events()
    assert event["type"] == "session.activity"
    assert event["session"]["repo"] == "github.com/acme/api"


def test_garbage_input_never_raises(configured):
    hook.run("not json")
    hook.run("[]")
    hook.run(json.dumps({"hook_event_name": "Stop"}))
    hook.run(json.dumps({"session_id": "x", "hook_event_name": "PreToolUse"}))
    assert _events() == []


def test_hook_prints_nothing(configured, git_repo, capsys):
    _run(session_id="s5", hook_event_name="SessionStart", cwd=str(git_repo), source="startup")
    _run(session_id="s5", hook_event_name="UserPromptSubmit", cwd=str(git_repo), prompt="ENG-1")
    captured = capsys.readouterr()
    assert captured.out == ""
