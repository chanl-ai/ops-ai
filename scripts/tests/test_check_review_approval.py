"""The review that approves a rise, read from GitHub (stubbed here), by failure mode: no review, a review by someone the
list does not name, a comment from a listed maintainer, and a review withdrawn are each `required`; a listed
maintainer's approval is `approved`, and `required` fails a rise while `approved` passes it."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import baseline_history as h  # pyright: ignore[reportMissingImports]
import check_review_approval as r  # pyright: ignore[reportMissingImports]

LISTED = {h.login_hash("maintainer")}


def review(login: str, state: str, at: str = "1") -> dict[str, str]:
    return {"login": login, "state": state, "at": at}


def test_no_review_and_a_review_by_an_unlisted_login_are_required() -> None:
    assert r.status([], LISTED) == "required"
    assert r.status([review("builder", "APPROVED")], LISTED) == "required"


def test_a_listed_maintainers_approval_is_approved_and_a_comment_or_a_withdrawal_is_not() -> None:
    assert r.status([review("Maintainer", "APPROVED")], LISTED) == "approved"
    assert r.status([review("maintainer", "COMMENTED")], LISTED) == "required"
    withdrawn = [review("maintainer", "APPROVED", "1"), review("maintainer", "CHANGES_REQUESTED", "2")]
    assert r.status(withdrawn, LISTED) == "required"


def test_a_listed_maintainers_own_pull_request_is_approved_without_a_review() -> None:
    assert r.status([], LISTED, author="Maintainer") == "approved"
    assert r.status([], LISTED, author="builder") == "required"
    assert r.status([], LISTED, author=None) == "required"


def test_the_script_proves_itself() -> None:
    assert r.self_test() == 0


def _git(repo: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=env).stdout.strip()


def _commit(repo: Path, name: str, text: str, msg: str) -> str:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", msg)
    return _git(repo, "rev-parse", "HEAD")


def test_an_approval_given_before_a_later_rise_does_not_count(tmp_path: Path) -> None:
    """A review names the commit it was given on. Rows raised after it were never seen by the reviewer."""
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, "sites/portable-baseline.txt", "# h\n2 raw a.py\n", "begin")
    reviewed = _commit(tmp_path, "sites/portable-baseline.txt", "# h\n3 raw a.py\n", "a rise the reviewer saw")
    head = _commit(tmp_path, "sites/portable-baseline.txt", "# h\n9 raw a.py\n", "a later rise")
    on = lambda commit: {"login": "maintainer", "state": "APPROVED", "at": "1", "commit": commit}  # noqa: E731

    def since(commit: str) -> bool:
        return h.rose_since(tmp_path, commit, head)

    assert r.status([on(head)], LISTED, head, since) == "approved"
    assert r.status([on(reviewed)], LISTED, head, since) == "required"
    assert r.status([{"login": "maintainer", "state": "APPROVED", "at": "1"}], LISTED, head, since) == "required"
    assert r.status([on("0" * 40)], LISTED, head, since) == "required"


def test_an_approval_before_commits_that_raise_nothing_still_counts(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, "sites/portable-baseline.txt", "# h\n2 raw a.py\n", "begin")
    reviewed = _commit(tmp_path, "sites/portable-baseline.txt", "# h\n3 raw a.py\n", "a rise the reviewer saw")
    _commit(tmp_path, "docs/x.md", "words\n", "a doc")
    head = _commit(tmp_path, "sites/portable-baseline.txt", "# h\n1 raw a.py\n", "a fall")
    assert h.rose_since(tmp_path, reviewed, head) is False
    given = {"login": "maintainer", "state": "APPROVED", "at": "1", "commit": reviewed}
    assert r.status([given], LISTED, head, lambda c: h.rose_since(tmp_path, c, head)) == "approved"


def test_the_head_list_counts_only_for_the_pull_request_that_adds_the_list(tmp_path: Path) -> None:
    """develop and main have no list today: a pull request that does not add one has no approver, and one that edits a
    list the base has is judged by the base's list."""
    _git(tmp_path, "init", "-q")
    listing = ".github/standards-maintainers.txt"
    base = _commit(tmp_path, "a.txt", "1\n", "begin")
    none = _commit(tmp_path, "b.txt", "2\n", "no list in this pull request")
    assert r.allowed_list(tmp_path, base, none) == set()
    adds = _commit(tmp_path, listing, f"{h.login_hash('owner')}\n", "adds the list")
    assert r.allowed_list(tmp_path, base, adds) == {h.login_hash("owner")}
    base_with = adds
    own = _commit(tmp_path, listing, f"{h.login_hash('owner')}\n{h.login_hash('me')}\n", "lists itself")
    assert r.allowed_list(tmp_path, base_with, own) == {h.login_hash("owner")}
