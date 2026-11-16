"""Whether a pull request has an approving review from a listed maintainer, read from GitHub, not from any commit.

A commit message can say anything, and a builder that writes its own approval passed the old trailer check. The review
is the proof: its author is GitHub's, and a pull request cannot add its own reviewer to the list, because the list read
is the one at the pull request's base.

  python3 scripts/check_review_approval.py --repo <owner/name> --pr <number> --base <sha>   # approved or required
  python3 scripts/check_review_approval.py --self-test

CI's `maintainer-review` job sets OPS_STANDARDS_REVIEW to what this prints before it runs `make checks-commits`: a rise
in a baseline fails on `required` and passes on `approved` (scripts/baseline_history.py).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseline_history

ROOT = Path(__file__).resolve().parents[1]


def approving(reviews: list[dict[str, Any]], allowed: set[str]) -> bool:
    """Whether a listed maintainer's latest review (a later review replaces an earlier one, so a dismissed or changed
    mind counts) is an approval. `reviews` are {login, state, at} in any order."""
    latest: dict[str, tuple[str, str]] = {}
    for review in reviews:
        login = str(review.get("login") or "").lower()
        if not login or review.get("state") in ("COMMENTED", "PENDING"):
            continue
        if login not in latest or str(review.get("at") or "") >= latest[login][0]:
            latest[login] = (str(review.get("at") or ""), str(review.get("state") or ""))
    return any(
        state == "APPROVED" and baseline_history.login_hash(login) in allowed for login, (_, state) in latest.items()
    )


def fetch(repo: str, pr: int) -> list[dict[str, Any]]:
    """The pull request's reviews through the GitHub API (`gh` signed in with the job's token)."""
    done = subprocess.run(
        [
            "gh", "api", f"repos/{repo}/pulls/{pr}/reviews", "--paginate",
            "--jq", "[.[] | {login: .user.login, state: .state, at: .submitted_at}]",
        ],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    pages: list[dict[str, Any]] = []
    decoder, text, i = json.JSONDecoder(), done.stdout, 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        page, i = decoder.raw_decode(text, i)
        pages += page
    return pages


def status(reviews: list[dict[str, Any]], allowed: set[str]) -> str:
    return "approved" if approving(reviews, allowed) else "required"


def self_test() -> int:
    listed = {baseline_history.login_hash("maintainer")}
    cases = [
        ([], "required"),
        ([{"login": "someone", "state": "APPROVED", "at": "1"}], "required"),
        ([{"login": "maintainer", "state": "COMMENTED", "at": "1"}], "required"),
        ([{"login": "maintainer", "state": "APPROVED", "at": "1"}], "approved"),
        (
            [
                {"login": "maintainer", "state": "APPROVED", "at": "1"},
                {"login": "maintainer", "state": "CHANGES_REQUESTED", "at": "2"},
            ],
            "required",
        ),
    ]
    bad = [(r, want) for r, want in cases if status(r, listed) != want]
    print("self-test: FAILED" if bad else f"self-test: {len(cases)} cases behave")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--base", help="the pull request's base sha: its maintainers list is the one that counts")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not (args.repo and args.pr and args.base):
        parser.error("--repo, --pr and --base are required")
    allowed = baseline_history.maintainers_at(ROOT, args.base)
    # The pull request that adds the list has none at its base; that one time its own list counts, and its review is
    # the owner's.
    allowed = allowed or baseline_history.maintainers_at(ROOT, "HEAD")
    print(status(fetch(args.repo, args.pr), allowed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
