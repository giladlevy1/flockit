"""Role scoping: developers see themselves, leads see their teams, admins see the org."""

import pytest

from tests.conftest import ago, collector_token, event, send


@pytest.fixture
async def org(admin, make_user):
    platform = (await admin.post("/api/teams", json={"name": "Platform"})).json()
    payments = (await admin.post("/api/teams", json={"name": "Payments"})).json()
    lead = await make_user("Lee Lead", "lead", [platform["id"]])
    dev1 = await make_user("Dev One", "developer", [platform["id"]])
    dev2 = await make_user("Dev Two", "developer", [payments["id"]])
    for i, (who, repo) in enumerate(
        [(admin, "github.com/acme/infra"), (lead, "github.com/acme/api"), (dev1, "github.com/acme/api"),
         (dev2, "github.com/acme/billing")]
    ):
        token = await collector_token(who)
        await send(
            who,
            token,
            event("session.start", "s%d" % i, ago(hours=2), repo=repo, task_ref="ENG-7", agent_model="claude-opus-5"),
            event("session.end", "s%d" % i, ago(hours=1), end_reason="prompt_input_exit"),
        )
    return {"admin": admin, "lead": lead, "dev1": dev1, "dev2": dev2, "platform": platform, "payments": payments}


async def _owners(client, **params):
    page = (await client.get("/api/sessions", params=params)).json()
    return sorted(s["owner"]["name"] for s in page["items"])


async def test_admin_sees_organisation(org):
    assert await _owners(org["admin"]) == ["Ada Admin", "Dev One", "Dev Two", "Lee Lead"]


async def test_lead_sees_team(org):
    assert await _owners(org["lead"]) == ["Dev One", "Lee Lead"]
    me = (await org["lead"].get("/api/auth/me")).json()
    assert me["scope"] == "team"


async def test_developer_sees_self(org):
    assert await _owners(org["dev1"]) == ["Dev One"]
    assert await _owners(org["dev2"]) == ["Dev Two"]


async def test_filters_cannot_widen_scope(org):
    assert await _owners(org["dev1"], owner=org["dev2"].user_id) == []
    assert await _owners(org["lead"], team=org["payments"]["id"]) == []


async def test_session_detail_scoped(org):
    other = (await org["admin"].get("/api/sessions", params={"owner": org["dev2"].user_id})).json()["items"][0]
    assert (await org["dev1"].get("/api/sessions/" + other["id"])).status_code == 404
    assert (await org["admin"].get("/api/sessions/" + other["id"])).status_code == 200


async def test_summary_and_facets_scoped(org):
    s = (await org["dev1"].get("/api/sessions/summary")).json()
    assert s["sessions"] == 1 and s["people"] == 1
    f = (await org["dev1"].get("/api/sessions/facets")).json()
    assert [p["name"] for p in f["people"]] == ["Dev One"]
    assert f["repos"] == ["github.com/acme/api"]

    f = (await org["lead"].get("/api/sessions/facets")).json()
    assert sorted(p["name"] for p in f["people"]) == ["Dev One", "Lee Lead"]
    assert [t["name"] for t in f["teams"]] == ["Platform"]


async def test_people_list_scoped(org):
    names = sorted(u["name"] for u in (await org["lead"].get("/api/users")).json())
    assert names == ["Dev One", "Lee Lead"]
    assert len((await org["admin"].get("/api/users")).json()) == 4


async def test_filters(org):
    a = org["admin"]
    assert await _owners(a, repo="github.com/acme/api") == ["Dev One", "Lee Lead"]
    assert await _owners(a, team=org["payments"]["id"]) == ["Dev Two"]
    assert await _owners(a, q="billing") == ["Dev Two"]
    assert await _owners(a, q="dev one") == ["Dev One"]
    assert await _owners(a, status="live") == []
    assert len(await _owners(a, status="ended")) == 4
    assert len(await _owners(a, since=ago(minutes=30).isoformat())) == 0
    assert len(await _owners(a, since=ago(hours=3).isoformat())) == 4
    assert len(await _owners(a, model="claude-opus-5", vendor="claude-code")) == 4


async def test_overlap_detection(org):
    s = (await org["admin"].get("/api/sessions/summary")).json()
    assert s["overlaps"][0]["task_ref"] == "ENG-7"
    assert s["overlaps"][0]["people"] == ["Ada Admin", "Dev One", "Dev Two", "Lee Lead"]
    assert s["outcomes"]["completed"] == 4
    assert s["by_agent"][0]["model"] == "claude-opus-5"
    assert {r["repo"] for r in s["top_repos"]} == {"github.com/acme/api", "github.com/acme/infra", "github.com/acme/billing"}
    assert abs(s["agent_hours"] - 4.0) < 0.05


async def test_non_admins_cannot_manage_people(org):
    r = await org["lead"].post("/api/users", json={"email": "x@acme.dev", "name": "X", "password": "password-1"})
    assert r.status_code == 403
    r = await org["dev1"].post("/api/teams", json={"name": "Rogue"})
    assert r.status_code == 403


async def test_last_admin_is_protected(org):
    me = (await org["admin"].get("/api/auth/me")).json()["user"]
    r = await org["admin"].patch("/api/users/" + me["id"], json={"role": "developer"})
    assert r.status_code == 400
    r = await org["admin"].patch("/api/users/" + me["id"], json={"is_active": False})
    assert r.status_code == 400


async def test_team_membership_changes_lead_scope(org):
    await org["admin"].patch(
        "/api/teams/" + org["payments"]["id"], json={"name": "Payments", "member_ids": [org["dev2"].user_id, org["lead"].user_id]}
    )
    assert await _owners(org["lead"]) == ["Dev One", "Dev Two", "Lee Lead"]


async def test_duplicate_email_and_team(org):
    r = await org["admin"].post("/api/users", json={"email": "dev.one@acme.dev", "name": "Again", "password": "password-1"})
    assert r.status_code == 409
    r = await org["admin"].post("/api/teams", json={"name": "Platform"})
    assert r.status_code == 409


async def test_developer_sees_no_team_roster(org):
    teams = (await org["dev1"].get("/api/teams")).json()
    assert [t["name"] for t in teams] == ["Platform"]
    assert teams[0]["member_ids"] == [org["dev1"].user_id]


async def test_lead_sees_only_shared_team_names(org):
    # Dev One is also on Payments, which the lead is not part of.
    await org["admin"].patch("/api/users/" + org["dev1"].user_id, json={"team_ids": [org["platform"]["id"], org["payments"]["id"]]})
    users = {u["name"]: u for u in (await org["lead"].get("/api/users")).json()}
    assert [t["name"] for t in users["Dev One"]["teams"]] == ["Platform"]
    items = (await org["lead"].get("/api/sessions", params={"owner": org["dev1"].user_id})).json()["items"]
    assert items[0]["owner"]["teams"] == ["Platform"]
    admin_view = (await org["admin"].get("/api/sessions", params={"owner": org["dev1"].user_id})).json()["items"]
    assert admin_view[0]["owner"]["teams"] == ["Payments", "Platform"]
