from flockit_server import db
from flockit_server.queries import sweep_abandoned
from tests.conftest import ago, collector_token, event, send


async def _only(client):
    page = (await client.get("/api/sessions")).json()
    assert page["total"] == 1, page
    return page["items"][0]


async def test_full_lifecycle(admin):
    token = await collector_token(admin)
    meta = dict(repo="github.com/acme/api", branch="feature/ENG-1-x", task_ref="ENG-1", agent_model="claude-opus-5")
    r = await send(
        admin,
        token,
        event("session.start", "s1", ago(minutes=30), start_source="startup", agent_version="2.1.3", **meta),
        event("session.activity", "s1", ago(minutes=20), **meta),
        event("session.activity", "s1", ago(minutes=10), agent_model="claude-sonnet-5"),
        event("session.end", "s1", ago(minutes=5), end_reason="prompt_input_exit"),
    )
    assert r.json() == {"accepted": 4, "duplicates": 0, "rejected": 0}
    s = await _only(admin)
    assert s["owner"]["email"] == "ada@acme.dev"
    assert s["origin"] == "human"
    assert s["repo"] == "github.com/acme/api"
    assert s["task_ref"] == "ENG-1"
    assert s["agent_model"] == "claude-sonnet-5"
    assert s["models_used"] == ["claude-opus-5", "claude-sonnet-5"]
    assert s["agent_version"] == "2.1.3"
    assert s["turn_count"] == 2
    assert s["status"] == "ended"
    assert s["outcome"] == "completed"
    assert 1490 <= s["duration_seconds"] <= 1510


async def test_retries_are_idempotent(admin):
    token = await collector_token(admin)
    e = event("session.activity", "s1")
    await send(admin, token, e)
    r = await send(admin, token, e, e)
    assert r.json() == {"accepted": 0, "duplicates": 2, "rejected": 0}
    assert (await _only(admin))["turn_count"] == 1


async def test_out_of_order_and_late_start(admin):
    token = await collector_token(admin)
    await send(admin, token, event("session.end", "s1", ago(minutes=1), end_reason="logout"))
    await send(admin, token, event("session.start", "s1", ago(minutes=60), repo="github.com/acme/api"))
    s = await _only(admin)
    assert s["repo"] == "github.com/acme/api"
    assert s["status"] == "ended"
    assert 3500 <= s["duration_seconds"] <= 3700


async def test_empty_values_never_erase(admin):
    token = await collector_token(admin)
    await send(admin, token, event("session.start", "s1", repo="github.com/acme/api", branch="main"))
    await send(admin, token, event("session.activity", "s1"))
    s = await _only(admin)
    assert s["repo"] == "github.com/acme/api" and s["branch"] == "main"


async def test_session_seen_first_mid_flight(admin):
    token = await collector_token(admin)
    await send(admin, token, event("session.activity", "s1", repo="github.com/acme/api"))
    s = await _only(admin)
    assert s["status"] == "live"
    assert s["outcome"] == "unknown"


async def test_invalid_events_rejected_valid_ones_kept(admin):
    token = await collector_token(admin)
    bad_type = event("session.hack", "s1")
    bad_id = event("session.start", "../../etc")
    no_session = {"event_id": "not-a-uuid", "type": "session.start"}
    extra = event("session.start", "ok", prompt="SECRET PROMPT", transcript="SECRET")
    r = await send(admin, token, bad_type, bad_id, no_session, extra)
    assert r.json() == {"accepted": 1, "duplicates": 0, "rejected": 3}


async def test_unauthenticated_ingest(admin, client_factory):
    c = client_factory()
    r = await c.post("/api/ingest/events", json={"events": [event("session.start", "s1")]})
    assert r.status_code == 401
    r = await send(c, "flk_not-a-real-token", event("session.start", "s1"))
    assert r.status_code == 401


async def test_batch_size_limit(admin):
    token = await collector_token(admin)
    r = await send(admin, token, *[event("session.activity", "s%d" % i) for i in range(501)])
    assert r.status_code == 422


async def test_ownership_never_reassigned(admin, make_user):
    dev = await make_user("Dan Dev")
    ada_token, dan_token = await collector_token(admin), await collector_token(dev)
    await send(admin, ada_token, event("session.start", "shared-id"))
    r = await send(dev, dan_token, event("session.end", "shared-id", end_reason="logout"))
    assert r.json()["rejected"] == 1
    s = await _only(admin)
    assert s["owner"]["email"] == "ada@acme.dev" and s["status"] != "ended"


async def test_future_timestamps_are_clamped(admin):
    token = await collector_token(admin)
    await send(admin, token, event("session.start", "s1", ago(minutes=10)))
    await send(admin, token, event("session.activity", "s1", ago(days=-30)))
    s = await _only(admin)
    assert s["duration_seconds"] < 60 * 20


async def test_sweeper_abandons_and_activity_reopens(admin):
    token = await collector_token(admin)
    await send(admin, token, event("session.start", "old", ago(hours=10)))
    await send(admin, token, event("session.start", "fresh", ago(minutes=5)))
    async with db.sessionmaker()() as session:
        assert await sweep_abandoned(session) == 1
    page = (await admin.get("/api/sessions", params={"outcome": "abandoned"})).json()
    assert [s["status"] for s in page["items"]] == ["ended"]

    await send(admin, token, event("session.activity", "old"))
    page = (await admin.get("/api/sessions", params={"outcome": "abandoned"})).json()
    assert page["total"] == 0


async def test_end_reasons_map_to_outcomes(admin):
    token = await collector_token(admin)
    await send(
        admin,
        token,
        event("session.end", "a", end_reason="prompt_input_exit"),
        event("session.end", "b", end_reason="other"),
        event("session.end", "c", end_reason="clear"),
    )
    items = (await admin.get("/api/sessions")).json()["items"]
    assert sorted(s["outcome"] for s in items) == ["completed", "completed", "unknown"]


async def test_deactivated_user_cannot_ingest(admin, make_user):
    dev = await make_user("Dan Dev")
    token = await collector_token(dev)
    await admin.patch("/api/users/" + dev.user_id, json={"is_active": False})
    r = await send(dev, token, event("session.start", "s1"))
    assert r.status_code == 401
    assert (await dev.get("/api/auth/me")).status_code == 401
