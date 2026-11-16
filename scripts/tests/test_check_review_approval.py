"""The review that approves a rise, read from GitHub (stubbed here), by failure mode: no review, a review by someone the
list does not name, a comment from a listed maintainer, and a review withdrawn are each `required`; a listed
maintainer's approval is `approved`, and `required` fails a rise while `approved` passes it."""

from __future__ import annotations

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


def test_the_script_proves_itself() -> None:
    assert r.self_test() == 0
