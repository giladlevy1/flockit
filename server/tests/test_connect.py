import pytest

from flockit_server.settings import get_settings


@pytest.fixture
def wheel_dir(tmp_path, monkeypatch):
    (tmp_path / "flockit-0.1.0-py3-none-any.whl").write_bytes(b"PK fake wheel")
    monkeypatch.setenv("FLOCKIT_COLLECTOR_DIST", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


async def test_install_script_without_collector(client_factory, monkeypatch, tmp_path):
    monkeypatch.setenv("FLOCKIT_COLLECTOR_DIST", str(tmp_path / "missing"))
    get_settings.cache_clear()
    r = await client_factory().get("/install.sh")
    assert r.status_code == 503


async def test_install_script_points_at_this_server(wheel_dir, client_factory):
    c = client_factory()
    r = await c.get("/install.sh")
    assert r.status_code == 200
    assert 'SERVER="http://flockit.test"' in r.text
    assert 'WHEEL="flockit-0.1.0-py3-none-any.whl"' in r.text
    assert "--no-index" in r.text and "--disable-pip-version-check" in r.text
    assert "pypi.org" not in r.text and "github.com" not in r.text


async def test_public_url_override(wheel_dir, client_factory, monkeypatch):
    monkeypatch.setenv("FLOCKIT_PUBLIC_URL", "https://flockit.corp.internal/")
    get_settings.cache_clear()
    r = await client_factory().get("/install.sh")
    assert 'SERVER="https://flockit.corp.internal"' in r.text


async def test_wheel_download(wheel_dir, client_factory):
    c = client_factory()
    r = await c.get("/downloads/flockit-0.1.0-py3-none-any.whl")
    assert r.status_code == 200 and r.content == b"PK fake wheel"
    traversal = await c.get("/downloads/..%2Fetc%2Fpasswd")
    assert traversal.status_code != 200 and b"root:" not in traversal.content
    assert (await c.get("/downloads/other.whl")).status_code == 404


async def test_connect_info(wheel_dir, client_factory):
    info = (await client_factory().get("/api/connect")).json()
    assert info["collector_available"] is True
    assert info["install_command"] == "curl -fsSL http://flockit.test/install.sh | sh -s -- <token>"


async def test_unknown_api_path_is_json_404(client_factory):
    r = await client_factory().get("/api/nope")
    assert r.status_code == 404
