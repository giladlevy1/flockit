"""`flockit mcp`: the JSON-RPC layer the editor talks to.

Nothing here touches the network — `_get` and `_post` are replaced by a fake API. What is
under test is the protocol (one reply per request, no reply for a notification, an error
instead of a crash) and the formatters, which have to read people in both shapes the API
returns them in.
"""

import io
import json

import pytest

from flockit import __version__, mcp


class Api:
    """The Flockit API as the tools see it: a path in, a body out."""

    def __init__(self):
        self.bodies: dict = {}
        self.calls: list = []

    def get(self, path, **params):
        self.calls.append((path, params))
        return self._answer(path)

    def post(self, path, payload):
        self.calls.append((path, payload))
        return self._answer(path)

    def _answer(self, path):
        body = self.bodies.get(path, self.bodies.get(path.split("?")[0]))
        if isinstance(body, Exception):
            raise body
        return body


@pytest.fixture
def api(monkeypatch):
    fake = Api()
    monkeypatch.setattr(mcp, "_get", fake.get)
    monkeypatch.setattr(mcp, "_post", fake.post)
    return fake


def call(name: str, arguments: dict = None, request_id=1) -> dict:
    return mcp.handle({"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments or {}}})


def text_of(reply: dict) -> str:
    return reply["result"]["content"][0]["text"]


# --- the protocol ---------------------------------------------------------------------


def test_initialize_introduces_the_server_and_agrees_on_a_version():
    reply = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert reply["id"] == 1 and reply["jsonrpc"] == "2.0"
    result = reply["result"]
    assert result["serverInfo"] == {"name": "flockit", "version": __version__}
    assert result["protocolVersion"] == mcp.PROTOCOL
    assert result["capabilities"]["tools"] == {"listChanged": False}
    # A client that speaks an older version is answered in its own.
    older = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05"}})
    assert older["result"]["protocolVersion"] == "2024-11-05"


def test_notifications_get_no_reply_and_unknown_methods_get_an_error():
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}}) is None
    assert mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "ping"})["result"] == {}
    unknown = mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
    assert unknown["error"]["code"] == -32601 and "resources/list" in unknown["error"]["message"]
    # A notification is one-way, even when the method means nothing here.
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/progress"}) is None


def test_tools_list_describes_every_tool():
    tools = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    assert [t["name"] for t in tools] == [
        "search_sessions", "get_session", "recent_sessions", "ai_developers", "ai_developer",
        "my_tasks", "assign_task",
    ]
    for tool in tools:
        assert tool["description"].strip(), tool["name"]
        assert tool["inputSchema"]["type"] == "object" and isinstance(tool["inputSchema"]["properties"], dict)
    assert set(mcp.BY_NAME) == {t["name"] for t in tools}


# --- tools/call -----------------------------------------------------------------------


def test_a_good_call_returns_text(api):
    api.bodies["/api/tasks"] = {"items": [{"id": "t1", "status": "queued", "title": "Fix the flaky login test",
                                           "repo": "github.com/acme/api"}]}
    reply = call("my_tasks")
    assert reply["result"]["isError"] is False
    assert "Fix the flaky login test" in text_of(reply) and "github.com/acme/api" in text_of(reply)


def test_a_failing_call_comes_back_as_text_not_a_crash(api):
    api.bodies["/api/tasks"] = RuntimeError("Flockit returned 503")
    reply = call("my_tasks")
    assert reply["result"]["isError"] is True and text_of(reply) == "Flockit returned 503"
    # An unconfigured machine is the same kind of answer: something the editor can show.
    api.bodies["/api/tasks"] = mcp.NotConfigured("No editor token yet.")
    assert call("my_tasks")["result"]["isError"] is True


def test_an_unknown_tool_or_bad_arguments_are_errors_not_exceptions(api):
    unknown = call("delete_everything")
    assert unknown["result"]["isError"] is True and "No such tool" in text_of(unknown)
    missing = call("get_session", {})
    assert missing["result"]["isError"] is True and "Wrong arguments for get_session" in text_of(missing)
    extra = call("my_tasks", {"limit": 5})
    assert extra["result"]["isError"] is True and "Wrong arguments" in text_of(extra)
    not_an_object = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": "my_tasks", "arguments": ["oops"]}})
    assert not_an_object["result"]["isError"] is True


def test_assign_task_posts_and_reports_back(api):
    api.bodies["/api/tasks"] = {"id": "t9", "title": "Fix the thing", "status": "queued",
                                "assignee": {"id": "ai-1", "name": "Ada Bot"}}
    reply = call("assign_task", {"assignee_id": "ai-1", "title": "Fix the thing", "prompt": "Fix the thing."})
    assert "Assigned to Ada Bot" in text_of(reply) and "t9" in text_of(reply)
    path, payload = api.calls[-1]
    assert path == "/api/tasks" and payload["assignee_id"] == "ai-1" and payload["repo"] is None


# --- people come back in two shapes ------------------------------------------------------


@pytest.mark.parametrize(
    "candidates,expected",
    [
        (("Ada Bot", "Lee Lead"), "Ada Bot"),
        (({"id": "u1", "name": "Ada Bot"}, "Lee Lead"), "Ada Bot"),
        ((None, {"id": "u2", "name": "Lee Lead"}), "Lee Lead"),
        (("", {"id": "u2", "name": "Lee Lead"}), "Lee Lead"),
        (({"id": "u1"}, "Lee Lead"), "Lee Lead"),  # an id with no name is not a person to show
        ((None, None), "someone"),
    ],
)
def test_who_reads_a_person_whichever_shape_the_api_used(candidates, expected):
    assert mcp._who(*candidates) == expected


def test_search_and_session_detail_both_render_a_persons_name(api):
    """Search returns `actor`/`owner` as plain names; the session endpoint returns
    `{id, name}`. Both have to read as a person, or the editor shows "someone"."""
    api.bodies["/api/search"] = {
        "items": [{"session_id": "s1", "at": "2026-09-18T10:00:00Z", "snippet": "the <<checkout>> retry",
                   "session": {"title": "Checkout retries", "actor": "Ada Bot", "owner": "Lee Lead",
                               "repo": "github.com/acme/api"}}]
    }
    found = text_of(call("search_sessions", {"query": "checkout"}))
    assert "Ada Bot" in found and "**checkout**" in found and "s1" in found

    api.bodies["/api/sessions/s1"] = {"title": "Checkout retries", "repo": "github.com/acme/api",
                                      "actor": {"id": "u1", "name": "Ada Bot"},
                                      "owner": {"id": "u2", "name": "Lee Lead"},
                                      "started_at": "2026-09-18T10:00:00Z", "turn_count": 4,
                                      "files_touched": 2, "outcome": "succeeded"}
    api.bodies["/api/sessions/s1/transcript"] = {
        "items": [{"role": "user", "kind": "text", "content": "retries forever on 429"},
                  {"role": "assistant", "kind": "tool_use", "tool_name": "Bash", "content": "pytest -q"}]
    }
    detail = text_of(call("get_session", {"session_id": "s1"}))
    assert "Ada Bot" in detail and "**Developer:** retries forever on 429" in detail and "[Bash] pytest -q" in detail

    # And the other way round: neither formatter may assume the shape it usually sees.
    api.bodies["/api/search"]["items"][0]["session"]["actor"] = {"id": "u1", "name": "Ada Bot"}
    assert "Ada Bot" in text_of(call("search_sessions", {"query": "checkout"}))
    api.bodies["/api/sessions/s1"]["actor"] = "Ada Bot"
    assert "Ada Bot" in text_of(call("get_session", {"session_id": "s1"}))

    api.bodies["/api/sessions"] = {"items": [{"id": "s2", "title": "Rate limits", "owner": {"id": "u2", "name": "Lee Lead"},
                                              "repo": "github.com/acme/api", "started_at": "2026-09-17T09:00:00Z"}]}
    assert "Lee Lead" in text_of(call("recent_sessions", {}))
    # Nobody at all is still a sentence, not a KeyError.
    api.bodies["/api/sessions"] = {"items": [{"id": "s3", "title": "Orphan"}]}
    assert "someone" in text_of(call("recent_sessions", {}))


def test_ai_developer_listing_and_profile_read_the_nested_payloads(api):
    api.bodies["/api/ai-developers"] = [
        {"id": "ai-1", "name": "Ada Bot", "agent_vendor": "claude-code", "default_repo": "github.com/acme/web",
         "environment": {"name": "app-postgres"}, "stats": {"tasks": {"succeeded": 3}},
         "current_task": {"title": "Fix the thing"}}
    ]
    listed = text_of(call("ai_developers"))
    assert "workbench app-postgres" in listed and "3 task(s) done" in listed and "Fix the thing" in listed

    api.bodies["/api/ai-developers/ai-1"] = {
        "developer": {"name": "Ada Bot", "environment": {"name": "app-postgres", "description": "Postgres 16",
                                                         "services": [{"name": "db"}]}},
        "expertise": {"repos": [{"repo": "github.com/acme/web", "tasks": 3}], "areas": [{"area": "server", "files": 9}]},
        "tasks": [{"status": "succeeded", "title": "Fix the thing", "pr_url": "https://github.com/acme/web/pull/4"}],
    }
    profile = text_of(call("ai_developer", {"developer_id": "ai-1"}))
    assert "Workbench **app-postgres** (db)" in profile
    assert "github.com/acme/web (3)" in profile and "server (9)" in profile
    assert "succeeded: Fix the thing → https://github.com/acme/web/pull/4" in profile


def test_empty_results_say_so_rather_than_printing_nothing(api):
    api.bodies["/api/search"] = {"items": []}
    assert "No sessions mention" in text_of(call("search_sessions", {"query": "nothing"}))
    api.bodies["/api/sessions"] = {"items": []}
    assert text_of(call("recent_sessions", {})) == "No sessions match."
    api.bodies["/api/ai-developers"] = []
    assert "no AI developers yet" in text_of(call("ai_developers"))
    api.bodies["/api/tasks"] = {"items": []}
    assert text_of(call("my_tasks")) == "Nothing assigned to you."


# --- stdio ------------------------------------------------------------------------------


def test_serve_answers_one_line_per_request_and_ignores_the_rest(api):
    api.bodies["/api/tasks"] = {"items": []}
    stdin = io.StringIO(
        "\n".join(
            [
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                "",
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                "{ not json",
                json.dumps(["not", "an", "object"]),
                "   ",
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                            "params": {"name": "my_tasks", "arguments": {}}}),
            ]
        )
        + "\n"
    )
    stdout = io.StringIO()
    assert mcp.serve(stdin, stdout) == 0
    replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [r["id"] for r in replies] == [1, 2]
    assert replies[0]["result"]["serverInfo"]["name"] == "flockit"
    assert replies[1]["result"]["content"][0]["text"] == "Nothing assigned to you."


def test_a_tool_that_blows_up_unexpectedly_does_not_kill_the_server(api, monkeypatch):
    monkeypatch.setitem(mcp.BY_NAME, "my_tasks", ({}, lambda: (_ for _ in ()).throw(ZeroDivisionError("boom"))))
    stdout = io.StringIO()
    line = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "my_tasks"}})
    assert mcp.serve(io.StringIO(line + "\n"), stdout) == 0
    reply = json.loads(stdout.getvalue())
    assert reply["id"] == 7 and reply["error"]["code"] == -32603 and "ZeroDivisionError" in reply["error"]["message"]
