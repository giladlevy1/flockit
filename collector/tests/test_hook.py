import json

from flockit import hook, outbox


def _run(**data):
    hook.run(json.dumps(data))


def _all_events():
    events = outbox.snapshot()
    outbox.remove(e["event_id"] for e in events)
    return events


def _events():
    """Session metadata events only (transcripts are tested separately)."""
    return [e for e in _all_events() if e["type"] != "session.transcript"]


def test_unconfigured_collector_does_nothing(git_repo):
    _run(session_id="s1", hook_event_name="SessionStart", cwd=str(git_repo), source="startup")
    assert _events() == []


def test_task_id_links_the_session(configured, git_repo, transcript, monkeypatch):
    monkeypatch.setenv("FLOCKIT_TASK_ID", "0b6a3c1e-8f7d-4a4b-9c1d-2e3f4a5b6c7d")
    _run(session_id="s7", hook_event_name="SessionStart", cwd=str(git_repo), transcript_path=str(transcript), source="startup")
    (event,) = _events()
    assert event["session"]["task_id"] == "0b6a3c1e-8f7d-4a4b-9c1d-2e3f4a5b6c7d"


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


def test_metadata_events_never_carry_conversation(configured, git_repo, transcript):
    common = dict(session_id="s2", cwd=str(git_repo), transcript_path=str(transcript))
    _run(hook_event_name="SessionStart", source="startup", **common)
    _run(hook_event_name="UserPromptSubmit", prompt="deploy with AKIA" + "IOSFODNN7EXAMPLE", **common)
    _run(hook_event_name="Stop", **common)
    raw = json.dumps(_events())
    for forbidden in ("SECRET PROMPT", "SECRET ANSWER", "AKIA", "ghp_", "deploy:", str(git_repo), "session.jsonl"):
        assert forbidden not in raw


def test_transcript_is_sent_redacted(configured, git_repo, transcript):
    lines = [
        {"type": "user", "uuid": "u1", "timestamp": "2026-09-19T10:00:00Z",
         "message": {"role": "user", "content": "deploy with AKIA" + "IOSFODNN7EXAMPLE from " + str(git_repo) + "/infra"}},
        {"type": "assistant", "uuid": "a1", "timestamp": "2026-09-19T10:00:02Z",
         "message": {"id": "msg_1", "model": "claude-opus-5", "usage": {"input_tokens": 10, "output_tokens": 5},
                     "content": [{"type": "tool_use", "id": "t1", "name": "Edit",
                                  "input": {"file_path": str(git_repo) + "/src/app.py", "old_string": "a", "new_string": "b"}}]}},
        {"type": "user", "uuid": "u2", "timestamp": "2026-09-19T10:00:03Z",
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
    ]
    transcript.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    common = dict(session_id="s9", cwd=str(git_repo), transcript_path=str(transcript))
    _run(hook_event_name="SessionStart", source="startup", **common)
    _run(hook_event_name="Stop", **common)
    events = [e for e in _all_events() if e["type"] == "session.transcript"]
    assert len(events) == 1
    t = events[0]["transcript"]
    raw = json.dumps(t)
    assert "AKIA" not in raw and str(git_repo) not in raw
    assert t["title"].startswith("deploy with [REDACTED] from ./infra")
    assert [m["kind"] for m in t["messages"]] == ["text", "tool_use", "tool_result"]
    assert t["messages"][2]["tool_name"] == "Edit"
    assert t["files"] == [{"path": "src/app.py", "edits": 1}]
    assert t["usage"]["input"] == 10 and t["usage"]["output"] == 5
    # the next Stop sends only what is new
    _run(hook_event_name="Stop", **common)
    assert [e for e in _all_events() if e["type"] == "session.transcript"] == []


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
