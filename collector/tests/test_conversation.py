import json

from flockit import conversation
from flockit.conversation import Converter, read_new

GH = "ghp_" + "1234567890abcdefghijABCDEFGHIJ123456"


def _assistant(uid, mid, blocks, usage=None, model="claude-opus-5"):
    return {"type": "assistant", "uuid": uid, "timestamp": "2026-09-19T10:00:00Z",
            "message": {"id": mid, "model": model, "content": blocks, "usage": usage or {}}}


def test_usage_counted_once_per_api_message():
    # Claude Code writes one transcript line per content block, each repeating the same usage.
    usage = {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 50}
    entries = [
        _assistant("a1", "msg_1", [{"type": "text", "text": "Looking."}], usage),
        _assistant("a2", "msg_1", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}], usage),
    ]
    c = Converter("/repo")
    batch = c.feed(entries)
    assert batch.usage == {"input": 100, "output": 20, "cache_read": 1000, "cache_write": 50}
    # a later read that repeats msg_1 is not counted again
    again = Converter("/repo", c.state()).feed([_assistant("a3", "msg_1", [], usage)])
    assert again.usage["input"] == 0


def test_meta_sidechain_and_thinking_are_skipped():
    entries = [
        {"type": "user", "uuid": "u1", "message": {"role": "user", "content": "<command-name>/clear</command-name>"}},
        {"type": "user", "uuid": "u2", "isMeta": True, "message": {"role": "user", "content": "Caveat: internal"}},
        {"type": "user", "uuid": "u3", "isSidechain": True, "message": {"role": "user", "content": "subagent chatter"}},
        _assistant("a1", "m1", [{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "Done."}]),
        {"type": "summary", "summary": "x"},
    ]
    batch = Converter(None).feed(entries)
    assert [(m["role"], m["content"]) for m in batch.messages] == [("assistant", "Done.")]
    assert batch.title is None


def test_secrets_and_paths_in_every_kind_of_message(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = str(tmp_path / "code" / "api")
    entries = [
        {"type": "user", "uuid": "u1", "message": {"role": "user", "content": f"use {GH} to push"}},
        _assistant("a1", "m1", [{"type": "tool_use", "id": "t1", "name": "Bash",
                                  "input": {"command": f"GITHUB_TOKEN={GH} git push", "description": "Push"}}]),
        {"type": "user", "uuid": "u2", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": f"fatal: {root}/x denied for {GH}"}]}},
        _assistant("a2", "m2", [{"type": "tool_use", "id": "t2", "name": "Write",
                                  "input": {"file_path": f"{root}/.env", "content": "SECRET=1"}}]),
    ]
    batch = Converter(root).feed(entries)
    raw = json.dumps(batch.payload())
    assert GH not in raw and root not in raw and str(tmp_path) not in raw
    assert batch.messages[2]["content"].startswith("[error] fatal: ./x denied")
    assert batch.messages[2]["tool_name"] == "Bash"
    assert batch.files == {".env": 1}
    assert "SECRET=1" not in raw  # Write records the size, not the content


def test_long_text_is_clipped():
    entries = [_assistant("a1", "m1", [{"type": "text", "text": "x" * 50_000}])]
    msg = Converter(None).feed(entries).messages[0]
    assert len(msg["content"]) < conversation.MAX_TEXT + 100 and "more characters" in msg["content"]


def test_stream_json_result_event():
    entries = [
        {"type": "system", "subtype": "init", "session_id": "abc", "model": "claude-opus-5"},
        _assistant("a1", "m1", [{"type": "text", "text": "Fixed it."}]),
        {"type": "result", "subtype": "success", "is_error": False, "result": "Fixed it.", "total_cost_usd": 0.12},
    ]
    batch = Converter(None).feed(entries)
    assert batch.result["total_cost_usd"] == 0.12 and batch.model == "claude-opus-5"


def test_read_new_only_returns_complete_lines(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text('{"a": 1}\n{"b": 2}\n{"c":')
    entries, offset = read_new(str(path), 0)
    assert entries == [{"a": 1}, {"b": 2}]
    with open(path, "a") as fh:
        fh.write(' 3}\n')
    more, offset2 = read_new(str(path), offset)
    assert more == [{"c": 3}] and offset2 > offset
    assert read_new(str(path), offset2) == ([], offset2)


def test_sequence_continues_across_reads():
    c = Converter(None)
    c.feed([_assistant("a1", "m1", [{"type": "text", "text": "one"}])])
    second = Converter(None, c.state()).feed([_assistant("a2", "m2", [{"type": "text", "text": "two"}])])
    assert second.messages[0]["seq"] == 1
