import pytest

from flockit import taskref


@pytest.mark.parametrize(
    "branch,expected",
    [
        ("feature/ENG-123-login", "ENG-123"),
        ("eng-77-fix-typo", "ENG-77"),
        ("fix/gh-42", "#42"),
        ("issue-9-crash", "#9"),
        ("issues/1234", "#1234"),
        ("main", None),
        ("release/2026-09", None),
        ("feature/utf-8-support", None),
        (None, None),
    ],
)
def test_from_branch(branch, expected):
    assert taskref.from_branch(branch) == expected


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("please fix https://github.com/acme/api/issues/42 today", "https://github.com/acme/api/issues/42"),
        ("look at https://linear.app/acme/issue/ENG-5/login-broken.", "https://linear.app/acme/issue/ENG-5"),
        ("see https://acme.atlassian.net/browse/OPS-12?focusedCommentId=1", "https://acme.atlassian.net/browse/OPS-12"),
        ("working on PAY-881 now", "PAY-881"),
        ("convert to UTF-8 please", None),
        ("just refactor this", None),
        ("", None),
    ],
)
def test_from_prompt(prompt, expected):
    assert taskref.from_prompt(prompt) == expected


def test_env_wins(monkeypatch):
    monkeypatch.setenv("FLOCKIT_TASK_REF", "OPS-1")
    assert taskref.from_env() == "OPS-1"


def test_env_invalid_ignored(monkeypatch):
    monkeypatch.setenv("FLOCKIT_TASK_REF", "not a ref")
    assert taskref.from_env() is None
