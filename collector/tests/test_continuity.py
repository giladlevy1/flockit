"""Snapshots of a developer's working tree, taken while they work.

These run against real git, because the whole point of the design is *which* git plumbing
is used: a temporary index, `commit-tree`, and a ref outside `refs/heads`. Faking git would
test the mock instead of the property that matters — that a developer never notices.
"""

import os
import subprocess

import pytest

from flockit import continuity
from tests.test_work import git


@pytest.fixture
def repo(tmp_path):
    """A checkout with a remote, one commit, and a developer mid-change."""
    bare = tmp_path / "remote" / "app.git"
    bare.mkdir(parents=True)
    git(bare, "init", "-q", "--bare", "-b", "main")
    work = tmp_path / "code" / "app"
    work.mkdir(parents=True)
    git(work, "init", "-q", "-b", "main")
    (work / "billing.py").write_text("def total(): return 1\n")
    git(work, "add", ".")
    git(work, "commit", "-qm", "billing")
    git(work, "remote", "add", "origin", str(bare))
    git(work, "push", "-q", "origin", "main")
    # Mid-session: an edit, an untracked file, and something staged.
    (work / "billing.py").write_text("def total(): return 2  # half-done\n")
    (work / "scratch.py").write_text("print('scratch')\n")
    (work / "staged.txt").write_text("staged\n")
    git(work, "add", "staged.txt")
    return work, bare


def status(work) -> str:
    return subprocess.run(["git", "status", "--porcelain"], cwd=work, capture_output=True, text=True).stdout


def show(work, sha, path) -> str:
    return subprocess.run(["git", "show", f"{sha}:{path}"], cwd=work, capture_output=True, text=True).stdout


SESSION = "0199a1f2-dead-beef-cafe-000000000001"


def test_a_snapshot_captures_what_the_developer_has_not_committed(repo):
    work, _ = repo
    taken = continuity.snapshot(str(work), SESSION)
    assert taken and taken["ref"] == f"refs/flockit/wip/{SESSION}"
    # Everything they had, committed or not, is in the snapshot's tree.
    assert show(work, taken["sha"], "billing.py") == "def total(): return 2  # half-done\n"
    assert show(work, taken["sha"], "scratch.py") == "print('scratch')\n"
    assert show(work, taken["sha"], "staged.txt") == "staged\n"


def test_the_developer_never_notices(repo):
    """The reason this is safe to run every minute on someone's machine."""
    work, _ = repo
    before_status = status(work)
    before_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=work, capture_output=True, text=True).stdout
    before_branch = subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=work, capture_output=True, text=True).stdout

    continuity.snapshot(str(work), SESSION)

    assert status(work) == before_status  # nothing staged, unstaged or cleaned up
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=work, capture_output=True, text=True).stdout == before_head
    assert subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=work, capture_output=True, text=True).stdout == before_branch
    # No stash, and the snapshot is not on any branch.
    assert subprocess.run(["git", "stash", "list"], cwd=work, capture_output=True, text=True).stdout == ""
    assert "flockit" not in before_branch


def test_the_snapshot_is_pushed_as_a_shadow_ref_not_a_branch(repo):
    work, bare = repo
    taken = continuity.snapshot(str(work), SESSION)
    assert taken["pushed"] is True
    heads = subprocess.run(["git", "ls-remote", "--heads", str(bare)], capture_output=True, text=True).stdout
    assert "flockit" not in heads  # it must not show up as a branch, or trigger CI
    refs = subprocess.run(["git", "ls-remote", str(bare)], capture_output=True, text=True).stdout
    assert f"refs/flockit/wip/{SESSION}" in refs


def test_a_second_snapshot_replaces_the_first(repo):
    """It is a snapshot of now, not a history of every minute."""
    work, bare = repo
    first = continuity.snapshot(str(work), SESSION)
    (work / "billing.py").write_text("def total(): return 3\n")
    (work / "scratch.py").unlink()
    second = continuity.snapshot(str(work), SESSION)
    assert second["sha"] != first["sha"]
    assert show(work, second["sha"], "billing.py") == "def total(): return 3\n"
    # A file they deleted is absent from the new tree, so continuing elsewhere deletes it too.
    listing = subprocess.run(["git", "ls-tree", "-r", "--name-only", second["sha"]], cwd=work, capture_output=True, text=True).stdout
    assert "scratch.py" not in listing and "billing.py" in listing
    on_remote = subprocess.run(["git", "ls-remote", str(bare), f"refs/flockit/wip/{SESSION}"], capture_output=True, text=True).stdout
    assert second["sha"] in on_remote


def test_ignored_files_stay_out_of_it(repo):
    """Snapshots follow .gitignore: build output and .env do not leave the machine."""
    work, _ = repo
    (work / ".gitignore").write_text("secrets.env\nnode_modules/\n")
    (work / "secrets.env").write_text("API_KEY=sk-live-should-never-be-copied\n")
    (work / "node_modules").mkdir()
    (work / "node_modules" / "big.js").write_text("x" * 1000)
    taken = continuity.snapshot(str(work), SESSION)
    listing = subprocess.run(["git", "ls-tree", "-r", "--name-only", taken["sha"]], cwd=work, capture_output=True, text=True).stdout
    assert "secrets.env" not in listing and "node_modules" not in listing


def test_a_repository_with_no_commits_has_nothing_to_snapshot(tmp_path):
    fresh = tmp_path / "new"
    fresh.mkdir()
    git(fresh, "init", "-q", "-b", "main")
    (fresh / "a.py").write_text("x = 1\n")
    assert continuity.snapshot(str(fresh), SESSION) is None


def test_without_a_remote_the_work_is_still_snapshotted_locally(tmp_path):
    """Someone working on a repository they have not pushed anywhere still gets a local ref;
    it simply cannot be continued elsewhere, and the server is told so."""
    work = tmp_path / "solo"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    (work / "a.py").write_text("x = 1\n")
    git(work, "add", ".")
    git(work, "commit", "-qm", "one")
    (work / "a.py").write_text("x = 2\n")
    taken = continuity.snapshot(str(work), SESSION)
    assert taken and taken["pushed"] is False
    assert show(work, taken["sha"], "a.py") == "x = 2\n"


@pytest.mark.parametrize("bad", ["../../etc/passwd", "a b", "-delete", "", "x" * 80])
def test_a_session_id_that_is_not_one_never_reaches_a_ref(repo, bad):
    work, _ = repo
    assert continuity.snapshot(str(work), bad) is None


def test_missing_git_is_not_an_error_the_developer_sees(repo, monkeypatch):
    """The agent takes snapshots in the background; a failure must be silent and harmless."""
    work, _ = repo
    monkeypatch.setenv("PATH", os.path.dirname(os.sys.executable))
    assert continuity.snapshot(str(work), SESSION) in (None,)
