"""Always-on sessions: a closed laptop hands the work to the person's own AI developer.

The rules here are mostly about *not* doing it. A handoff starts a paid agent on someone's
repository without them asking at that moment, so every condition is a condition to refuse.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from flockit_server import continuity
from flockit_server.db import sessionmaker
from flockit_server.models import AgentSession, Machine, User, WorkflowRun
from tests.conftest import collector_token, event, send

HELLO = {"name": "dev-macbook", "platform": "darwin", "version": "0.3.0", "capabilities": {"claude": True}}
SESSION = "0199a1f2-dead-beef-cafe-000000000001"
REF = f"refs/flockit/wip/{SESSION}"
SHA = "cbfad8cd7b1f9e0a1b2c3d4e5f60718293a4b5c6"


@pytest.fixture
async def dev(admin, make_user):
    """A developer with a laptop, always-on sessions turned on, and a live session."""
    person = await make_user("Noa Levi")
    token = await collector_token(person)
    r = await person.put("/api/me/continuity", json={"enabled": True, "default_repo": "github.com/acme/api"})
    assert r.status_code == 200, r.text
    await person.post("/api/agent/poll?wait=0", json=HELLO, headers={"Authorization": "Bearer " + token})
    await send(person, token, event("session.start", SESSION, repo="github.com/acme/api", branch="feature/x"))
    await send(person, token, event("session.activity", SESSION))
    return {"person": person, "token": token, "runner": (await admin.post("/api/runners", json={"name": "box"})).json()}


async def wip(client, token, pushed=True, external_id=SESSION):
    return await client.post(
        "/api/agent/sessions/wip",
        json={"external_id": external_id, "ref": f"refs/flockit/wip/{external_id}", "sha": SHA, "pushed": pushed},
        headers={"Authorization": "Bearer " + token},
    )


async def go_offline(minutes: float = 5) -> None:
    """Move the laptop's heartbeat and the session's last activity into the past."""
    async with sessionmaker()() as s:
        for row in (await s.execute(select(Machine).where(Machine.kind == "laptop"))).scalars():
            row.last_seen_at = row.last_seen_at - timedelta(minutes=minutes)
        for row in (await s.execute(select(AgentSession))).scalars():
            row.last_seen_at = row.last_seen_at - timedelta(minutes=minutes)
        await s.commit()


async def handovers() -> list:
    async with sessionmaker()() as s:
        return list((await s.execute(select(WorkflowRun).where(WorkflowRun.trigger == "continuity"))).scalars().unique())


async def sweep() -> int:
    async with sessionmaker()() as s:
        return await continuity.sweep(s)


# --- turning it on ---------------------------------------------------------------------


async def test_turning_it_on_creates_one_ai_developer_that_belongs_to_you(dev, admin):
    state = (await dev["person"].get("/api/me/continuity")).json()
    assert state["enabled"] is True and state["agent"]["name"] == "Noa's agent"

    # It is a real member of the organisation, and it is theirs.
    listed = [a for a in (await admin.get("/api/ai-developers")).json() if a["name"] == "Noa's agent"]
    assert len(listed) == 1 and listed[0]["default_repo"] == "github.com/acme/api"

    # Turning it off and on again does not create a second one.
    await dev["person"].put("/api/me/continuity", json={"enabled": False})
    await dev["person"].put("/api/me/continuity", json={"enabled": True})
    again = (await admin.get("/api/ai-developers")).json()
    assert len([a for a in again if a["name"] == "Noa's agent"]) == 1


async def test_off_by_default(make_user):
    person = await make_user("Sam Okafor")
    assert (await person.get("/api/me/continuity")).json() == {
        "enabled": False,
        "agent": None,
        "runners": 0,
        "last_handover": None,
    }


# --- the handoff ------------------------------------------------------------------------


async def test_a_closed_laptop_hands_the_session_to_their_agent(dev):
    assert (await wip(dev["person"], dev["token"])).json()["continuable"] is True
    assert await sweep() == 0  # the laptop is still reporting: nothing to do

    await go_offline()
    assert await sweep() == 1
    task = (await handovers())[0]
    assert task.status.value == "queued" and task.repo == "github.com/acme/api"
    assert task.trigger_payload["start_sha"] == SHA and task.trigger_payload["start_ref"] == REF

    # The prompt hands over the work, not a fresh brief.
    assert "continuing a coding session" in task.prompt and "do not start over" in task.prompt

    # The session is closed as continued, and points at what continued it.
    async with sessionmaker()() as s:
        row = (await s.execute(select(AgentSession).where(AgentSession.external_id == SESSION))).scalar_one()
        assert row.end_reason == "continued" and row.continued_by_run_id == task.id
        assert row.ended_at is not None

    assert await sweep() == 0  # and it is never handed over twice


async def test_it_waits_for_the_machine_to_actually_be_gone(dev):
    """Someone thinking with their laptop open is the most common way to look idle."""
    await wip(dev["person"], dev["token"])
    async with sessionmaker()() as s:
        for row in (await s.execute(select(AgentSession))).scalars():
            row.last_seen_at = row.last_seen_at - timedelta(minutes=10)  # quiet session…
        await s.commit()
    assert await sweep() == 0  # …but the laptop is still beating, so no handoff


async def test_nothing_to_continue_from_is_not_continued(dev):
    """A snapshot that never reached the remote cannot be picked up anywhere else."""
    await wip(dev["person"], dev["token"], pushed=False)
    await go_offline()
    assert await sweep() == 0


async def test_it_is_off_unless_the_person_asked(dev):
    await dev["person"].put("/api/me/continuity", json={"enabled": False})
    await wip(dev["person"], dev["token"])
    await go_offline()
    assert await sweep() == 0


async def test_yesterdays_session_is_not_resurrected(dev):
    await wip(dev["person"], dev["token"])
    await go_offline(minutes=continuity.STALE_AFTER_MINUTES + 10)
    assert await sweep() == 0


async def test_their_agent_takes_one_thing_at_a_time(dev, admin):
    """A laptop that flaps should not start three agents on the same repository."""
    await wip(dev["person"], dev["token"])
    await go_offline()
    assert await sweep() == 1
    await send(dev["person"], dev["token"], event("session.start", "second-session", repo="github.com/acme/api"))
    await wip(dev["person"], dev["token"], external_id="second-session")
    await go_offline()
    assert await sweep() == 0  # its first handover is still running
    assert len(await handovers()) == 1


# --- the snapshot endpoint ---------------------------------------------------------------


async def test_a_snapshot_can_only_be_reported_for_your_own_session(dev, make_user):
    other = await make_user("Tom Becker")
    stolen = await wip(other, await collector_token(other))
    assert stolen.status_code == 404  # not their session, and not a hint that it exists
    async with sessionmaker()() as s:
        row = (await s.execute(select(AgentSession).where(AgentSession.external_id == SESSION))).scalar_one()
        assert row.wip_sha is None


@pytest.mark.parametrize(
    "ref,sha",
    [
        ("refs/heads/main", SHA),  # only Flockit's own shadow refs
        ("refs/flockit/wip/../../heads/main", SHA),
        ("refs/flockit/wip/x", "; rm -rf /"),
        ("refs/flockit/wip/x", "nothex"),
    ],
)
async def test_a_snapshot_reference_that_is_not_one_is_refused(dev, ref, sha):
    r = await dev["person"].post(
        "/api/agent/sessions/wip",
        json={"external_id": SESSION, "ref": ref, "sha": sha, "pushed": True},
        headers={"Authorization": "Bearer " + dev["token"]},
    )
    assert r.status_code == 422, r.text


async def test_the_agent_is_told_whether_to_take_snapshots_at_all(dev, make_user):
    poll = await dev["person"].post(
        "/api/agent/poll?wait=0", json=HELLO, headers={"Authorization": "Bearer " + dev["token"]}
    )
    assert poll.json()["continuity"] == "auto"

    quiet = await make_user("Lena Novak")
    token = await collector_token(quiet)
    off = await quiet.post("/api/agent/poll?wait=0", json=HELLO, headers={"Authorization": "Bearer " + token})
    assert off.json()["continuity"] == "off"


async def test_the_personal_agent_is_a_normal_ai_developer_for_everything_else(dev, admin):
    """It appears where AI developers appear, and its work is visible like any other."""
    await wip(dev["person"], dev["token"])
    await go_offline()
    await sweep()
    async with sessionmaker()() as s:
        agent = (await s.execute(select(User).where(User.name == "Noa's agent"))).scalar_one()
        assert agent.personal_for_id is not None and agent.sponsor_id == agent.personal_for_id
    profile = (await admin.get(f"/api/ai-developers/{agent.id}")).json()
    assert [t["title"].startswith("Continue:") for t in profile["tasks"]] == [True]
    assert (await dev["person"].get("/api/me/continuity")).json()["last_handover"]["status"] == "queued"


async def test_continuity_is_recorded_in_the_audit_log(dev, admin):
    await wip(dev["person"], dev["token"])
    await go_offline()
    await sweep()
    actions = [e["action"] for e in (await admin.get("/api/audit")).json()["items"]]
    assert "session.continued" in actions and "user.continuity" in actions


async def test_both_ends_of_a_handoff_link_to_each_other(dev, admin):
    """Whoever opens either session should be able to follow the work across the gap."""
    await wip(dev["person"], dev["token"])
    await go_offline()
    await sweep()
    task = (await handovers())[0]

    mine = (await dev["person"].get("/api/sessions?q=&limit=50")).json()["items"]
    interrupted = next(s for s in mine if s["title"] is None or s["continued_by"])
    assert interrupted["continued_by"]["id"] == str(task.id)
    assert interrupted["continued_by"]["title"].startswith("Continue:")

    # Once the AI developer's session starts, it points back at the one it took over.
    anon_headers = {"Authorization": "Bearer " + dev["runner"]["token"]}
    claim = (
        await dev["person"].post("/api/runner/poll?wait=0", json={"name": "box", "platform": "linux",
                                 "version": "0.3.0", "capabilities": {"docker": True}, "capacity": 1},
                                 headers=anon_headers)
    ).json()["task"]
    assert claim["start_sha"] == SHA and claim["start_ref"] == REF
    await send(dev["person"], claim["ingest_token"], event("session.start", "cloud-session", repo="github.com/acme/api"))
    cloud = next(s for s in (await admin.get("/api/sessions?limit=50")).json()["items"] if s["id"] != interrupted["id"] and s["continues"])
    assert cloud["continues"]["session_id"] == interrupted["id"]
