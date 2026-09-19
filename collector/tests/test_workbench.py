"""The workbench a runner builds beside a sandbox: what it refuses to hand to docker,
what it reuses, and what it is allowed to delete.

No docker here. `_docker` is replaced by a fake that records every command and answers
from a small world model, so the assertions are about the command lines themselves —
that is where a bad image name or a stray flag would do its damage.
"""

import subprocess

import pytest

from flockit import workbench
from flockit.workbench import Workbench

IMAGE = "ghcr.io/acme/agent:1"


def service(**kw) -> dict:
    s = {
        "name": "db",
        "image": "postgres:16-alpine",
        "env": {"POSTGRES_PASSWORD": "flockit"},
        "url_env": "DATABASE_URL",
        "url": "postgresql://app:flockit@db:5432/app",
        "ready": "pg_isready -U app",
        "data_path": "/var/lib/postgresql/data",
    }
    s.update(kw)
    return s


def spec(**kw) -> dict:
    body = {
        "id": "7f1c2d3e-aaaa-bbbb-cccc-ddddeeeeffff",
        "name": "app-postgres",
        "services": [service()],
        "variables": {"CUSTOMER": "acme"},
        "secret_names": ["OPENAI_API_KEY"],
        "setup_script": 'psql "$DATABASE_URL" -f db/schema.sql\n',
        "persistent": True,
    }
    body.update(kw)
    return body


class Docker:
    """Stands in for the docker CLI. It remembers which networks, containers and volumes
    exist, so reuse and first-build behave differently, as they do on a real runner."""

    def __init__(self, networks=(), containers=None, volumes=(), ready_failures=0):
        self.calls: list[list[str]] = []
        self.networks = set(networks)
        self.containers = dict(containers or {})
        self.volumes = set(volumes)
        self.ready_failures = ready_failures
        self.ready_calls = 0

    def __call__(self, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
        self.calls.append(list(args))
        return self._answer(list(args))

    @staticmethod
    def _ok(stdout: str = "") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(["docker"], 0, stdout, "")

    @staticmethod
    def _no(stderr: str = "No such object") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(["docker"], 1, "", stderr)

    def _answer(self, args):
        head = args[:2]
        if head == ["network", "inspect"]:
            return self._ok() if args[2] in self.networks else self._no()
        if head == ["network", "create"]:
            self.networks.add(args[2])
            return self._ok()
        if head == ["network", "rm"]:
            self.networks.discard(args[2])
            return self._ok()
        if head == ["volume", "inspect"]:
            return self._ok() if args[2] in self.volumes else self._no()
        if head == ["volume", "create"]:
            self.volumes.add(args[2])
            return self._ok()
        if head == ["volume", "rm"]:
            self.volumes.discard(args[2])
            return self._ok()
        if args[0] == "inspect":
            name = args[-1]
            return self._ok(self.containers[name] + "\n") if name in self.containers else self._no()
        if args[0] == "run":
            self.containers[args[args.index("--name") + 1]] = "running"
            return self._ok()
        if args[0] == "start":
            self.containers[args[1]] = "running"
            return self._ok()
        if args[0] == "rm":
            self.containers.pop(args[-1], None)
            return self._ok()
        if args[0] == "exec":
            self.ready_calls += 1
            return self._no() if self.ready_calls <= self.ready_failures else self._ok()
        return self._ok()

    # --- reading back what was run ------------------------------------------------
    def commands(self, *first: str) -> list[list[str]]:
        return [c for c in self.calls if c[: len(first)] == list(first)]

    @property
    def text(self) -> str:
        return "\n".join(" ".join(c) for c in self.calls)


@pytest.fixture
def docker(monkeypatch):
    fake = Docker()
    monkeypatch.setattr(workbench, "_docker", fake)
    monkeypatch.setattr(workbench.time, "sleep", lambda _: None)  # readiness polling without the wait
    return fake


# --- what never reaches a command line ---------------------------------------------


def test_clean_keeps_well_formed_services_and_drops_the_rest():
    cleaned = workbench._clean(
        spec(
            services=[
                service(name="bad-image", image="-rm -rf"),
                service(name="spaced", image="evil image"),
                service(name="lower-env", env={"postgres_password": "x"}),
                service(name="newline", env={"POSTGRES_PASSWORD": "x\n-v /:/host"}),
                service(name="relative", data_path="var/lib/data"),
                service(name="dotdot", data_path="/var/lib/../../etc"),
                service(),
            ]
        )
    )
    assert [s["name"] for s in cleaned["services"]] == ["lower-env", "newline", "relative", "dotdot", "db"]
    dropped = {s["name"]: s for s in cleaned["services"]}
    # The service survives; only the part that was malformed is thrown away.
    assert dropped["lower-env"]["env"] == {} and dropped["newline"]["env"] == {}
    assert dropped["relative"]["data_path"] == "" and dropped["dotdot"]["data_path"] == ""
    assert dropped["db"] == service()
    assert cleaned["variables"] == {"CUSTOMER": "acme"} and cleaned["secret_names"] == ["OPENAI_API_KEY"]


def test_clean_drops_variables_and_secret_names_that_are_not_variable_names():
    cleaned = workbench._clean(
        spec(variables={"CUSTOMER": "acme", "customer": "x", "PLAN": "one\ntwo"}, secret_names=["OK", "not-ok"])
    )
    assert cleaned["variables"] == {"CUSTOMER": "acme"} and cleaned["secret_names"] == ["OK"]


def test_a_malicious_spec_never_becomes_a_docker_flag(docker):
    Workbench(spec(services=[service(name="--privileged"), service(name="ok", image="--volume=/:/host")]), IMAGE).up()
    assert docker.commands("run") == []  # both services were dropped, so nothing was started
    assert "--privileged" not in docker.text and "/:/host" not in docker.text


# --- bringing one up -----------------------------------------------------------------


def test_up_creates_the_network_starts_each_service_and_waits_for_it(docker):
    docker.ready_failures = 2  # the database is still booting the first two times we ask
    bench = Workbench(spec(services=[service(), service(name="cache", image="redis:7-alpine", ready="redis-cli ping",
                                              url_env="REDIS_URL", url="redis://cache:6379/0", data_path="/data")]), IMAGE)
    bench.up()
    assert docker.commands("network", "create") == [["network", "create", bench.network]]
    run = docker.commands("run")
    assert [c[c.index("--name") + 1] for c in run] == [bench.container("db"), bench.container("cache")]
    for cmd, name in zip(run, ("db", "cache")):
        assert cmd[cmd.index("--network") + 1] == bench.network
        assert cmd[cmd.index("--network-alias") + 1] == name
        assert cmd[cmd.index("-v") + 1].startswith(bench.volume(name) + ":")
        assert cmd[-1] == {"db": "postgres:16-alpine", "cache": "redis:7-alpine"}[name]
    assert ["-e", "POSTGRES_PASSWORD=flockit"] == run[0][run[0].index("-e"):run[0].index("-e") + 2]
    # It kept asking until the readiness command finally succeeded, and only then returned.
    assert len(docker.commands("exec")) == 4  # two failures for db, then db, then cache
    assert bench.docker_args() == ["--network", bench.network]


def test_an_existing_network_is_not_created_again(docker):
    bench = Workbench(spec(), IMAGE)
    docker.networks.add(bench.network)
    bench.up()
    assert docker.commands("network", "create") == []


def test_a_service_that_is_already_running_is_reused(docker):
    bench = Workbench(spec(), IMAGE)
    docker.containers[bench.container("db")] = "running"
    docker.volumes.add(bench.volume("db"))
    bench.up()
    assert docker.commands("run") == [] and docker.commands("start") == []
    assert docker.commands("exec")  # it is still checked before the agent is let near it


def test_a_stopped_service_is_started_rather_than_rebuilt(docker):
    bench = Workbench(spec(), IMAGE)
    docker.containers[bench.container("db")] = "exited"
    docker.volumes.add(bench.volume("db"))
    bench.up()
    assert docker.commands("start") == [["start", bench.container("db")]]
    assert docker.commands("run") == []


def test_a_service_that_will_not_start_is_an_error(docker, monkeypatch):
    monkeypatch.setattr(workbench, "_docker", lambda *a, **kw: Docker._no("no such image"))
    with pytest.raises(RuntimeError, match="could not start db"):
        Workbench(spec(), IMAGE).up()


# --- seeding once ---------------------------------------------------------------------


def test_the_setup_script_runs_once_and_only_after_it_has_succeeded(docker):
    bench = Workbench(spec(), IMAGE)
    bench.up()
    assert docker.commands("volume", "create") == [["volume", "create", bench.volume("db")]]
    assert bench.setup_command() == 'psql "$DATABASE_URL" -f db/schema.sql\n'

    # A seed that failed is not recorded, so the next task tries again rather than leaving
    # the agent with a half-built database forever.
    docker.containers.clear()
    docker.calls.clear()
    retry = Workbench(spec(), IMAGE)
    retry.up()
    assert retry.setup_command() is not None

    # Once it actually succeeds the runner says so, and it never runs again — nothing
    # overwrites what the agent did yesterday.
    retry.mark_seeded()
    docker.containers.clear()
    docker.calls.clear()
    again = Workbench(spec(), IMAGE)
    again.up()
    assert docker.commands("run") and again.setup_command() is None


def test_a_workbench_without_a_setup_script_has_nothing_to_run(docker):
    bench = Workbench(spec(setup_script=""), IMAGE)
    bench.up()
    assert bench.setup_command() is None


def test_a_workbench_that_keeps_no_data_still_seeds_exactly_once(docker):
    """Seeding is tracked by its own marker, not by a service volume, so a workbench with
    nothing persistent behaves like every other one."""
    stateless = spec()
    stateless["services"][0].pop("data_path")
    bench = Workbench(stateless, IMAGE)
    bench.up()
    assert bench.setup_command() is not None
    bench.mark_seeded()

    again = Workbench(stateless, IMAGE)
    again.up()
    assert again.setup_command() is None


def test_a_workbench_with_no_services_at_all_seeds_exactly_once(docker):
    bench = Workbench(spec(services=[]), IMAGE)
    bench.up()
    assert bench.setup_command() is not None
    bench.mark_seeded()

    again = Workbench(spec(services=[]), IMAGE)
    again.up()
    assert again.setup_command() is None


# --- what the agent reads ---------------------------------------------------------------


def test_env_names_the_services_and_the_workbench():
    bench = Workbench(
        spec(services=[service(), service(name="cache", image="redis:7-alpine", url_env="REDIS_URL",
                               url="redis://cache:6379/0", data_path="/data")]),
        IMAGE,
    )
    assert bench.env() == {
        "CUSTOMER": "acme",
        "DATABASE_URL": "postgresql://app:flockit@db:5432/app",
        "REDIS_URL": "redis://cache:6379/0",
        "FLOCKIT_WORKBENCH": "app-postgres",
    }


def test_a_service_with_no_url_adds_no_variable():
    bench = Workbench(spec(services=[service(url_env="", url="")], variables={}), IMAGE)
    assert bench.env() == {"FLOCKIT_WORKBENCH": "app-postgres"}
    assert bench.docker_args() == ["--network", bench.network]


# --- taking one down ---------------------------------------------------------------------


def test_a_throwaway_workbench_is_removed_with_its_data(docker):
    bench = Workbench(spec(persistent=False), IMAGE)
    bench.up()
    docker.calls.clear()
    bench.down()
    assert docker.commands("rm") == [["rm", "-f", bench.container("db")]]
    assert docker.commands("volume", "rm") == [["volume", "rm", bench.volume("db")], ["volume", "rm", bench.marker()]]
    assert docker.commands("network", "rm") == [["network", "rm", bench.network]]


def test_a_persistent_workbench_is_left_exactly_where_it_is(docker):
    """The whole point of a workbench is that yesterday's schema is still there today."""
    bench = Workbench(spec(persistent=True), IMAGE)
    bench.up()
    docker.calls.clear()
    bench.down()
    assert docker.calls == []
    assert bench.volume("db") in docker.volumes and bench.container("db") in docker.containers
