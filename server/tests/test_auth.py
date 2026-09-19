import httpx

from tests.conftest import collector_token


async def test_first_run_setup(client_factory):
    c = client_factory()
    assert (await c.get("/api/setup")).json() == {"needs_setup": True}
    r = await c.post("/api/setup", json={"org_name": "Acme", "name": "Ada", "email": "ADA@acme.dev", "password": "password-1"})
    assert r.status_code == 201
    me = (await c.get("/api/auth/me")).json()
    assert me["user"]["email"] == "ada@acme.dev"
    assert me["user"]["role"] == "admin"
    assert me["scope"] == "organisation"
    assert me["org"]["name"] == "Acme"
    assert (await c.get("/api/setup")).json() == {"needs_setup": False}


async def test_setup_only_once(admin, client_factory):
    r = await client_factory().post(
        "/api/setup", json={"org_name": "Evil", "name": "Eve", "email": "eve@x.dev", "password": "password-1"}
    )
    assert r.status_code == 409


async def test_setup_validates(client_factory):
    c = client_factory()
    r = await c.post("/api/setup", json={"org_name": "A", "name": "A", "email": "nope", "password": "short"})
    assert r.status_code == 422


async def test_login_logout(admin, client_factory):
    c = client_factory()
    assert (await c.post("/api/auth/login", json={"email": "ada@acme.dev", "password": "wrong-pass"})).status_code == 401
    assert (await c.post("/api/auth/login", json={"email": "nobody@acme.dev", "password": "x"})).status_code == 401
    assert (await c.post("/api/auth/login", json={"email": "Ada@Acme.dev", "password": "password-1"})).status_code == 200
    assert (await c.get("/api/auth/me")).status_code == 200
    await c.post("/api/auth/logout")
    assert (await c.get("/api/auth/me")).status_code == 401


async def test_cookie_is_httponly(client_factory):
    c = client_factory()
    r = await c.post("/api/setup", json={"org_name": "A", "name": "A", "email": "a@a.dev", "password": "password-1"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


async def test_mutations_require_csrf_header(admin, app):
    cookies = admin.cookies
    raw = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://flockit.test", cookies=cookies)
    assert (await raw.get("/api/auth/me")).status_code == 200
    r = await raw.post("/api/tokens", json={"name": "x"})
    assert r.status_code == 403


async def test_change_password(admin, client_factory):
    r = await admin.post("/api/auth/password", json={"current_password": "nope-nope", "new_password": "password-2"})
    assert r.status_code == 400
    r = await admin.post("/api/auth/password", json={"current_password": "password-1", "new_password": "password-2"})
    assert r.status_code == 200
    c = client_factory()
    assert (await c.post("/api/auth/login", json={"email": "ada@acme.dev", "password": "password-2"})).status_code == 200


async def test_collector_tokens(admin, client_factory):
    token = await collector_token(admin)
    assert token.startswith("flk_")
    listed = (await admin.get("/api/tokens")).json()
    assert len(listed) == 1 and "token" not in listed[0]
    assert token.startswith(listed[0]["prefix"])

    c = client_factory()
    r = await c.get("/api/ingest/whoami", headers={"Authorization": "Bearer " + token})
    assert r.json()["user"]["email"] == "ada@acme.dev"

    await admin.delete("/api/tokens/" + listed[0]["id"])
    r = await c.get("/api/ingest/whoami", headers={"Authorization": "Bearer " + token})
    assert r.status_code == 401


async def test_login_cookie_is_not_a_collector_token(admin):
    assert (await admin.get("/api/ingest/whoami")).status_code == 401


async def test_security_headers(admin):
    r = await admin.get("/api/health")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "connect-src 'self'" in csp
    assert r.headers["x-frame-options"] == "DENY"
