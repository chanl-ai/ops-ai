#!/usr/bin/env python3
"""Reads the STAGING_HOLD repository variable (env HOLD) for .github/workflows/deploy-staging.yml.

A hold names the release under test: `X.Y.Z: reason`. BRANCHES is the release and hotfix branches on origin, space
separated; SHA is the commit being deployed (default HEAD). A branch whose head is an ancestor of SHA
is already merged, protects nothing and is ignored (one `notice=` line each); a head that cannot be read or compared
keeps the freeze. Prints the lines `state=`, `text=`, `pin=` and any `notice=`; `pin=` is the one reason a develop
merge is not deployed (a branch freeze, a live hold, or both;
empty when it is deployed). Exits 1 only for an invalid hold. States: none (no hold),
active (the release is not tagged yet, so staging stays frozen), ignored (tag vX.Y.Z exists: the hold is stale and the
deploy goes on), invalid (no `X.Y.Z:` prefix). Run in a checkout that holds the tags. Stdlib only; tests:
scripts/tests/test_staging_hold.py.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

PREFIX = re.compile(r"^(\d+\.\d+\.\d+):\s*(.*)$")


def judge(hold: str, tagged: set[str]) -> tuple[str, str]:
    hold = hold.strip()
    if not hold:
        return "none", ""
    m = PREFIX.match(hold)
    if not m:
        return "invalid", f"STAGING_HOLD '{hold}' must start with the release it waits for, as 'X.Y.Z: reason'"
    if f"v{m.group(1)}" in tagged:
        return "ignored", f"STAGING_HOLD for {m.group(1)} is stale: tag v{m.group(1)} exists, so the hold is ignored"
    return "active", hold


def head_of(branch: str) -> str:
    """The branch head commit: the remote-tracking ref, else a fetch of it. Empty when neither works (fail closed)."""

    def rev(ref: str) -> str:
        r = subprocess.run(
            ["git", "rev-parse", "--verify", "-q", f"{ref}^{{commit}}"], capture_output=True, text=True, check=False
        )
        return r.stdout.strip() if r.returncode == 0 else ""

    found = rev(f"refs/remotes/origin/{branch}")
    if found:
        return found
    fetched = subprocess.run(["git", "fetch", "-q", "origin", f"refs/heads/{branch}"], capture_output=True, check=False)
    return rev("FETCH_HEAD") if fetched.returncode == 0 else ""


def merged(branch: str, sha: str) -> bool:
    head = head_of(branch)
    if not head:
        return False
    return (
        subprocess.run(["git", "merge-base", "--is-ancestor", head, sha], capture_output=True, check=False).returncode
        == 0
    )


def main() -> int:
    tags = subprocess.run(["git", "tag", "--list", "v[0-9]*"], capture_output=True, text=True, check=False).stdout
    state, text = judge(os.environ.get("HOLD", ""), set(tags.split()))
    sha = os.environ.get("SHA", "").strip() or "HEAD"
    listed = os.environ.get("BRANCHES", "").split()
    ignored = [b for b in listed if merged(b, sha)]
    branches = " ".join(b for b in listed if b not in ignored)
    notices = "".join(f"notice={b} is merged into develop, freeze ignored\n" for b in ignored)
    parts = ([f"staging is frozen for {branches}"] if branches else []) + (
        [f"STAGING_HOLD is set: {text}"] if state == "active" else []
    )
    # The reason a develop merge is not deployed: a release or hotfix branch on origin, a live hold, or both.
    print(f"{notices}state={state}\ntext={text}\npin={'; '.join(parts)}")
    return 1 if state == "invalid" else 0


if __name__ == "__main__":
    sys.exit(main())
