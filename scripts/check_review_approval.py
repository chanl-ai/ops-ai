"""Whether a pull request has an approving review from a listed maintainer, read from GitHub, not from any commit.

A commit message can say anything, and a builder that writes its own approval passed the old trailer check. The review
is the proof: its author is GitHub's, and a pull request cannot add its own reviewer to the list, because the list read
is the one at the pull request's base. A pull request authored by a listed maintainer counts as approved, since GitHub
refuses self-approval.

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
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseline_history

ROOT = Path(__file__).resolve().parents[1]


def approving(
    reviews: list[dict[str, Any]],
    allowed: set[str],
    head: str | None = None,
    rose_since: Callable[[str], bool] = lambda _commit: True,
) -> bool:
    """Whether a listed maintainer's latest review (a later review replaces an earlier one, so a dismissed or changed
    mind counts) is an approval. `reviews` are {login, state, at, commit} in any order. With `head`, an approval
    counts only on the head commit, or on an earlier one when `rose_since(commit)` says nothing was raised after it:
    the reviewer did not see rows raised later."""
    latest: dict[str, tuple[str, str, str]] = {}
    for review in reviews:
        login = str(review.get("login") or "").lower()
        if not login or review.get("state") in ("COMMENTED", "PENDING"):
            continue
        if login not in latest or str(review.get("at") or "") >= latest[login][0]:
            latest[login] = (
                str(review.get("at") or ""),
                str(review.get("state") or ""),
                str(review.get("commit") or ""),
            )
    return any(
        state == "APPROVED"
        and baseline_history.login_hash(login) in allowed
        and (head is None or commit == head or (bool(commit) and not rose_since(commit)))
        for login, (_, state, commit) in latest.items()
    )


def fetch(repo: str, pr: int) -> list[dict[str, Any]]:
    """The pull request's reviews through the GitHub API (`gh` signed in with the job's token)."""
    done = subprocess.run(
        [
            "gh", "api", f"repos/{repo}/pulls/{pr}/reviews", "--paginate",
            "--jq", "[.[] | {login: .user.login, state: .state, at: .submitted_at, commit: .commit_id}]",
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


def fetch_author(repo: str, pr: int) -> str:
    """The pull request author's login through the GitHub API."""
    done = subprocess.run(
        ["gh", "api", f"repos/{repo}/pulls/{pr}", "--jq", ".user.login"], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def status(
    reviews: list[dict[str, Any]],
    allowed: set[str],
    head: str | None = None,
    rose_since: Callable[[str], bool] = lambda _commit: True,
    author: str | None = None,
) -> str:
    # The sole listed maintainer authors these pull requests and GitHub refuses self-approval, so a review can never
    # arrive. Their own pull request counts as approved until a second maintainer account is listed.
    if author and baseline_history.login_hash(author.lower()) in allowed:
        return "approved"
    return "approved" if approving(reviews, allowed, head, rose_since) else "required"


def allowed_list(root: Path, base: str, head: str = "HEAD") -> set[str]:
    """Who may approve: the list at the pull request's base. The head's list counts only for the one pull request that
    adds the file (the base has none and the head has one); where neither has a list, nobody may approve."""
    listed = baseline_history.maintainers_at(root, base)
    if listed or baseline_history.has_maintainers(root, base):
        return listed
    return baseline_history.maintainers_at(root, head)


def local(run: Callable[..., Any] = subprocess.run) -> str:
    """The status of the pull request open for this branch, read through `gh`: `required` whenever it cannot be read
    (no pull request yet, no gh, offline), since a rise nobody can show was approved is not approved."""
    try:

        def out(*cmd: str) -> str:
            return str(run(list(cmd), cwd=ROOT, capture_output=True, text=True, check=True).stdout).strip()

        pr = json.loads(out("gh", "pr", "view", "--json", "number,baseRefName,headRefOid"))
        repo = out("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
        base = out("git", "rev-parse", f"origin/{pr['baseRefName']}")
        head = pr["headRefOid"]
        return status(
            fetch(repo, int(pr["number"])), allowed_list(ROOT, base), head,
            lambda c: baseline_history.rose_since(ROOT, c, "HEAD"), fetch_author(repo, int(pr["number"])),
        )  # fmt: skip
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        return "required"


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
    if status([], listed, author="Maintainer") != "approved" or status([], listed, author="someone") != "required":
        bad.append(("author listed, no reviews", "approved"))

    def no_gh(*_a: Any, **_k: Any) -> Any:
        raise FileNotFoundError("gh")

    if local(no_gh) != "required":  # nothing readable must never read as approved
        bad.append(("local without gh", "required"))
    print("self-test: FAILED" if bad else f"self-test: {len(cases)} cases behave")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--base", help="the pull request's base sha: its maintainers list is the one that counts")
    parser.add_argument("--head", default="HEAD", help="the pull request's head sha, which a review must be on")
    parser.add_argument("--local", action="store_true", help="read this branch's pull request through gh")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.local:
        print(local())
        return 0
    if not (args.repo and args.pr and args.base):
        parser.error("--repo, --pr and --base are required")
    allowed = allowed_list(ROOT, args.base)
    head = subprocess.run(
        ["git", "rev-parse", args.head], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    print(
        status(
            fetch(args.repo, args.pr), allowed, head, lambda c: baseline_history.rose_since(ROOT, c, head),
            fetch_author(args.repo, args.pr),
        )
    )  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
