"""Workbenches: who may change them, what the validator refuses, and how they reach a runner.

Everything in a workbench ends up on a docker command line, so the rejections below are the
interesting half of this file: a bad image name or a relative data path must never be stored.
"""

import uuid

import pytest

from flockit_server.routers.environments import PRESETS


def env_body(**kw) -> dict:
    body = {
        "name": "app-postgres",
        "description": "Postgres on the workbench network as `db`.",
        "services": [],
        "variables": {},
        "secret_names": [],
        "setup_script": None,
        "persistent": True,
    }
    body.update(kw)
    return body


def db_service(**kw) -> dict:
    s = {
        "name": "db",
        "image": "postgres:16-alpine",
        "env": {"POSTGRES_PASSWORD": "flockit", "POSTGRES_USER": "app", "POSTGRES_DB": "app"},
        "port": 5432,
        "url_env": "DATABASE_URL",
        "url": "postgresql://app:flockit@db:5432/app",
        "ready": "pg_isready -U app",
        "data_path": "/var/lib/postgresql/data",
    }
    s.update(kw)
    return s


@pytest.fixture
async def people(admin, make_user):
    dev = await make_user("Dev One")
    return {"admin": admin, "dev": dev}


async def test_only_admins_change_workbenches_but_anyone_may_read_them(people):
    admin, dev = people["admin"], people["dev"]
    assert (await dev.post("/api/environments", json=env_body())).status_code == 403
    created = await admin.post("/api/environments", json=env_body(services=[db_service()]))
    assert created.status_code == 201, created.text
    env = created.json()
    # Listing is a read: a developer needs it to tell which workbench an AI developer has.
    listed = await dev.get("/api/environments")
    assert listed.status_code == 200 and [e["name"] for e in listed.json()] == ["app-postgres"]
    assert (await dev.put(f"/api/environments/{env['id']}", json=env_body(name="renamed"))).status_code == 403
    assert (await dev.delete(f"/api/environments/{env['id']}")).status_code == 403
    renamed = await admin.put(f"/api/environments/{env['id']}", json=env_body(name="renamed", persistent=False))
    assert renamed.json()["name"] == "renamed" and renamed.json()["persistent"] is False
    assert (await admin.delete(f"/api/environments/{env['id']}")).status_code == 204
    assert (await admin.get("/api/environments")).json() == []


async def test_duplicate_names_are_refused(admin):
    assert (await admin.post("/api/environments", json=env_body())).status_code == 201
    assert (await admin.post("/api/environments", json=env_body())).status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        env_body(services=[db_service(image="-rm -rf")]),
        env_body(services=[db_service(image="evil image")]),
        env_body(services=[db_service(image="postgres:16 --privileged")]),
        env_body(services=[db_service(env={"database_url": "x"})]),
        env_body(services=[db_service(env={"DATA-BASE": "x"})]),
        env_body(services=[db_service(env={"POSTGRES_PASSWORD": "flockit\n-v /:/host"})]),
        env_body(services=[db_service(url="postgres://db\nmalice")]),
        env_body(services=[db_service(ready="pg_isready\nrm -rf /")]),
        env_body(services=[db_service(url_env="database_url")]),
        env_body(services=[db_service(data_path="var/lib/postgresql")]),
        env_body(services=[db_service(data_path="/var/lib/../../etc")]),
        env_body(services=[db_service(name="Db")]),
        env_body(services=[db_service(name="--privileged")]),
        env_body(services=[db_service(name="db"), db_service(name="db", image="redis:7-alpine")]),
        env_body(services=[db_service(name=f"s{i}") for i in range(5)]),
        env_body(variables={"lower": "x"}),
        env_body(variables={"OK": "one\ntwo"}),
        env_body(secret_names=["openai-key"]),
        env_body(name="App Postgres"),
        env_body(name="9lives"),
        env_body(name="-dash-first"),
    ],
)
async def test_validator_refuses_anything_a_shell_could_misread(admin, body):
    r = await admin.post("/api/environments", json=body)
    assert r.status_code == 422, r.text
    assert (await admin.get("/api/environments")).json() == []


async def test_a_postgres_workbench_survives_the_round_trip(admin):
    body = env_body(
        services=[db_service()],
        variables={"CUSTOMER": "acme"},
        secret_names=["OPENAI_API_KEY"],
        setup_script='psql "$DATABASE_URL" -f db/schema.sql\n',
        persistent=True,
    )
    created = (await admin.post("/api/environments", json=body)).json()
    fetched = [e for e in (await admin.get("/api/environments")).json() if e["id"] == created["id"]][0]
    assert fetched["services"] == [db_service()]
    assert fetched["variables"] == {"CUSTOMER": "acme"}
    assert fetched["secret_names"] == ["OPENAI_API_KEY"]
    assert fetched["setup_script"] == 'psql "$DATABASE_URL" -f db/schema.sql'
    assert fetched["persistent"] is True and fetched["used_by"] == []


async def test_a_workbench_in_use_cannot_be_deleted(admin):
    env = (await admin.post("/api/environments", json=env_body(services=[db_service()]))).json()
    ai = (await admin.post("/api/ai-developers", json={"name": "Ada Bot", "environment_id": env["id"]})).json()
    assert (await admin.delete(f"/api/environments/{env['id']}")).status_code == 409
    assert (await admin.get("/api/environments")).json()[0]["used_by"] == [{"id": ai["id"], "name": "Ada Bot"}]
    await admin.put(f"/api/ai-developers/{ai['id']}", json={"name": "Ada Bot", "environment_id": None})
    assert (await admin.delete(f"/api/environments/{env['id']}")).status_code == 204


async def test_assigning_a_workbench_shows_up_wherever_the_ai_developer_does(admin, make_user):
    dev = await make_user("Dev One")
    env = (await admin.post("/api/environments", json=env_body(services=[db_service()]))).json()
    ai = (await admin.post("/api/ai-developers", json={"name": "Ada Bot", "environment_id": env["id"]})).json()
    assert ai["environment"]["name"] == "app-postgres"
    listed = (await dev.get("/api/ai-developers")).json()[0]
    assert listed["environment"]["name"] == "app-postgres"
    assert [s["name"] for s in listed["environment"]["services"]] == ["db"]
    profile = (await dev.get(f"/api/ai-developers/{ai['id']}")).json()
    assert set(profile) >= {"developer", "expertise", "tasks", "sessions", "workflows"}
    assert profile["developer"]["environment"]["name"] == "app-postgres"
    assert profile["tasks"] == [] and profile["sessions"] == [] and profile["workflows"] == []
    stranger = await admin.post("/api/ai-developers", json={"name": "Ghost", "environment_id": str(uuid.uuid4())})
    assert stranger.status_code == 400  # a workbench id from nowhere is not silently ignored


async def test_every_preset_is_something_the_api_would_accept(admin):
    """A preset is a form the UI submits verbatim, so a preset that drifts out of spec is a
    workbench nobody can create from the starting points."""
    assert {p["key"] for p in PRESETS} == {"postgres", "postgres-redis", "customer", "none"}
    offered = (await admin.get("/api/environment-presets")).json()["items"]
    assert [p["key"] for p in offered] == [p["key"] for p in PRESETS]
    for preset in offered:
        r = await admin.post("/api/environments", json=preset["environment"])
        assert r.status_code == 201, f"{preset['key']}: {r.text}"
        assert r.json()["name"] == preset["environment"]["name"]


async def test_renaming_onto_a_taken_name_is_refused_the_same_way_creating_one_is(admin):
    """Creating a second `alpha` is a clean 409; renaming `beta` to `alpha` is too — the
    check has to be in update as well, or the rename reaches the unique index as a 500."""
    await admin.post("/api/environments", json=env_body(name="alpha"))
    beta = (await admin.post("/api/environments", json=env_body(name="beta"))).json()
    r = await admin.put(f"/api/environments/{beta['id']}", json=env_body(name="alpha"))
    assert r.status_code == 409, r.text
