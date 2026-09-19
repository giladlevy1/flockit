"""Laptop agents and AI-developer runners: claiming, reporting, attribution, transcripts, search."""

import uuid

import pytest

from tests.conftest import collector_token, event, send

HELLO = {"name": "dev-macbook", "platform": "darwin", "version": "0.2.0", "capabilities": {"claude": True}}


@pytest.fixture
async def setup(admin, make_user):
    platform = (await admin.post("/api/teams", json={"name": "Platform"})).json()
    lead = await make_user("Lee Lead", "lead", [platform["id"]])
    dev = await make_user("Dev One", "developer", [platform["id"]])
    ai = (await admin.post("/api/ai-developers", json={"name": "Ada Bot", "team_ids": [platform["id"]], "runner_pool": "linux"})).json()
    runner = (await admin.post("/api/runners", json={"name": "build-box", "pool": "linux"})).json()
    return {"admin": admin, "lead": lead, "dev": dev, "ai": ai, "runner": runner, "dev_token": await collector_token(dev)}


def bearer(token):
    return {"Authorization": "Bearer " + token}


async def new_task(client, assignee_id, **kw):
    body = {"title": "Upgrade deps", "prompt": "Bump minor versions.", "repo": "github.com/acme/api", "assignee_id": assignee_id}
    body.update(kw)
    r = await client.post("/api/tasks", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_laptop_gets_offers_once_then_claims_accepted_task(setup):
    dev, lead, token = setup["dev"], setup["lead"], setup["dev_token"]
    t = await new_task(lead, dev.user_id)
    poll = (await dev.post("/api/agent/poll", json=HELLO, headers=bearer(token))).json()
    assert poll["task"] is None and [o["id"] for o in poll["offers"]] == [t["id"]]
    again = (await dev.post("/api/agent/poll", json=HELLO, headers=bearer(token))).json()
    assert again["offers"] == []  # notified only once
    await dev.post(f"/api/tasks/{t['id']}/accept", json={"interactive": True})
    claim = (await dev.post("/api/agent/poll", json=HELLO, headers=bearer(token))).json()
    assert claim["task"]["id"] == t["id"] and claim["task"]["interactive"] is True
    assert "flockit/" in claim["task"]["prompt"] and "Upgrade deps" in claim["task"]["prompt"]
    state = (await dev.get(f"/api/tasks/{t['id']}")).json()
    assert state["status"] == "starting" and state["machine"]["name"] == "dev-macbook"
    inbox = (await dev.get("/api/tasks/inbox")).json()
    assert inbox["machines"][0]["online"] is True


async def test_headless_task_reported_by_laptop(setup):
    dev, lead, token = setup["dev"], setup["lead"], setup["dev_token"]
    await dev.patch("/api/auth/me", json={"dispatch_mode": "auto"})
    t = await new_task(lead, dev.user_id, mode="auto")
    claim = (await dev.post("/api/agent/poll", json=HELLO, headers=bearer(token))).json()
    assert claim["task"]["interactive"] is False
    # The collector hook links the session to the task via FLOCKIT_TASK_ID
    await send(dev, token, event("session.start", "sess-1", task_id=t["id"], repo="github.com/acme/api"))
    assert (await dev.get(f"/api/tasks/{t['id']}")).json()["status"] == "running"
    r = await dev.post(
        f"/api/agent/tasks/{t['id']}/status",
        json={"status": "succeeded", "result": "Done. Opened https://github.com/acme/api/pull/12", "cost_usd": 0.42},
        headers=bearer(token),
    )
    assert r.json()["status"] == "succeeded"
    final = (await lead.get(f"/api/tasks/{t['id']}")).json()
    assert final["pr_url"] == "https://github.com/acme/api/pull/12" and final["cost_usd"] == 0.42
    assert final["session_id"] is not None
    session = (await lead.get(f"/api/sessions/{final['session_id']}")).json()
    assert session["origin"] == "workflow" and session["task"]["id"] == t["id"]


async def test_interactive_task_completes_when_session_ends(setup):
    dev, lead, token = setup["dev"], setup["lead"], setup["dev_token"]
    t = await new_task(lead, dev.user_id)
    await dev.post(f"/api/tasks/{t['id']}/accept", json={"interactive": True})
    await dev.post("/api/agent/poll", json=HELLO, headers=bearer(token))
    await send(dev, token, event("session.start", "sess-2", task_id=t["id"]))
    await send(dev, token, event("session.end", "sess-2", task_id=t["id"], end_reason="prompt_input_exit"))
    assert (await dev.get(f"/api/tasks/{t['id']}")).json()["status"] == "succeeded"


async def test_other_people_cannot_touch_my_tasks(setup, make_user):
    dev, lead = setup["dev"], setup["lead"]
    t = await new_task(lead, dev.user_id)
    stranger = await make_user("Stranger")
    stoken = await collector_token(stranger)
    r = await stranger.post(f"/api/agent/tasks/{t['id']}/status", json={"status": "failed"}, headers=bearer(stoken))
    assert r.status_code == 404
    # a task_id in someone else's events does not link their session to my task
    await send(stranger, stoken, event("session.start", "evil", task_id=t["id"]))
    assert (await dev.get(f"/api/tasks/{t['id']}")).json()["session_id"] is None


async def test_runner_claims_ai_task_and_reports(setup, client_factory):
    lead, ai, runner = setup["lead"], setup["ai"], setup["runner"]
    assert runner["token"].startswith("frn_")
    t = await new_task(lead, ai["id"])
    anon = client_factory()
    rh = bearer(runner["token"])
    claim = (await anon.post("/api/runner/poll", json={**HELLO, "name": "build-box"}, headers=rh)).json()
    task = claim["task"]
    assert task["id"] == t["id"] and task["agent"]["name"] == "Ada Bot" and task["ingest_token"].startswith("flk_")
    assert (await anon.post("/api/runner/poll", json=HELLO, headers=rh)).json()["task"] is None

    # The sandbox reports the session with the per-task token: owned by the lead who assigned it, performed by the AI.
    itok = task["ingest_token"]
    transcript = {
        "title": "Upgrade deps",
        "messages": [
            {"id": "m1", "seq": 0, "role": "user", "kind": "text", "content": "Bump minor versions.", "at": "2026-09-19T10:00:00Z"},
            {"id": "m2", "seq": 1, "role": "assistant", "kind": "tool_use", "tool_name": "Bash", "content": "npm outdated", "at": "2026-09-19T10:00:05Z"},
            {"id": "m3", "seq": 2, "role": "assistant", "kind": "text", "content": "Upgraded vitest and zod; all tests pass.", "at": "2026-09-19T10:01:00Z"},
        ],
        "usage": {"input": 1200, "output": 300, "cache_read": 5000},
        "files": [{"path": "package.json", "edits": 2}, {"path": "package-lock.json", "edits": 1}],
    }
    await send(anon, itok, event("session.start", "ai-sess", agent_model="claude-opus-5"))
    ev = event("session.transcript", "ai-sess")
    ev["transcript"] = transcript
    await send(anon, itok, ev, ev)  # duplicate delivery must not double count
    r = await anon.post(f"/api/runner/tasks/{t['id']}/status", json={"status": "succeeded", "result": "PR: https://github.com/acme/api/pull/77"}, headers=rh)
    assert r.json()["status"] == "succeeded"
    # the per-task token dies with the task
    assert (await send(anon, itok, event("session.activity", "ai-sess"))).status_code == 401

    final = (await lead.get(f"/api/tasks/{t['id']}")).json()
    assert final["pr_url"] == "https://github.com/acme/api/pull/77" and final["machine"]["kind"] == "runner"
    s = (await lead.get(f"/api/sessions/{final['session_id']}")).json()
    assert s["owner"]["name"] == "Lee Lead" and s["actor"]["name"] == "Ada Bot" and s["actor"]["kind"] == "ai"
    assert s["tokens_input"] == 1200 and s["tokens_output"] == 300 and s["tool_calls"] == 1
    assert s["message_count"] == 3 and s["files_touched"] == 2 and s["title"] == "Upgrade deps"
    tr = (await lead.get(f"/api/sessions/{s['id']}/transcript")).json()["items"]
    assert [m["seq"] for m in tr] == [0, 1, 2]
    files = (await lead.get(f"/api/sessions/{s['id']}/files")).json()
    assert files[0] == {"path": "package.json", "edits": 2}
    ai_view = (await lead.get("/api/ai-developers")).json()[0]
    assert ai_view["stats"]["tasks"] == {"succeeded": 1} and ai_view["stats"]["tokens"] == 1500

    found = (await lead.get("/api/search", params={"q": "vitest"})).json()
    assert found["total"] == 1 and "<<vitest>>" in found["items"][0]["snippet"]
    assert found["items"][0]["session"]["actor"] == "Ada Bot"


async def test_search_is_scoped(setup, make_user):
    dev, token = setup["dev"], setup["dev_token"]
    ev = event("session.transcript", "s-private")
    ev["transcript"] = {"messages": [{"id": "x", "seq": 0, "role": "user", "kind": "text", "content": "rotate the payroll secret", "at": "2026-09-19T10:00:00Z"}]}
    await send(dev, token, event("session.start", "s-private"), ev)
    outsider = await make_user("Outsider")
    assert (await outsider.get("/api/search", params={"q": "payroll"})).json()["total"] == 0
    assert (await setup["lead"].get("/api/search", params={"q": "payroll"})).json()["total"] == 1
    assert (await dev.get("/api/search", params={"q": "payroll"})).json()["total"] == 1
    sid = (await dev.get("/api/sessions")).json()["items"][0]["id"]
    assert (await outsider.get(f"/api/sessions/{sid}/transcript")).status_code == 404


async def test_runner_pools_and_revocation(setup, client_factory):
    admin, lead = setup["admin"], setup["lead"]
    other = (await admin.post("/api/runners", json={"name": "mac-mini", "pool": "macos"})).json()
    await new_task(lead, setup["ai"]["id"])
    anon = client_factory()
    wrong_pool = (await anon.post("/api/runner/poll", json=HELLO, headers=bearer(other["token"]))).json()
    assert wrong_pool["task"] is None
    await admin.delete(f"/api/runners/{other['id']}")
    assert (await anon.post("/api/runner/poll", json=HELLO, headers=bearer(other["token"]))).status_code == 401
    runners = (await admin.get("/api/runners")).json()
    assert [r["name"] for r in runners] == ["build-box"] and "token" not in runners[0] or runners[0]["token"] is None


async def test_runner_cannot_report_foreign_task(setup, client_factory):
    t = await new_task(setup["lead"], setup["ai"]["id"])
    anon = client_factory()
    r = await anon.post(f"/api/runner/tasks/{t['id']}/status", json={"status": "succeeded"}, headers=bearer(setup["runner"]["token"]))
    assert r.status_code == 404  # not claimed by this runner
    r = await anon.post(f"/api/runner/tasks/{uuid.uuid4()}/status", json={"status": "succeeded"}, headers=bearer("frn_nope"))
    assert r.status_code == 401
