#!/usr/bin/env python3
"""Reads the STAGING_HOLD repository variable (env HOLD) for .github/workflows/deploy-staging.yml.

A hold names the release under test: `X.Y.Z: reason`. Prints `state=` and `text=` lines and exits 1 only for an invalid
hold. States: none (no hold), active (the release is not tagged yet, so staging stays frozen), ignored (tag vX.Y.Z
exists: the hold is stale and the deploy goes on), invalid (no `X.Y.Z:` prefix). Run in a checkout that holds the tags.
Stdlib only; tests: scripts/tests/test_staging_hold.py.
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


def main() -> int:
    tags = subprocess.run(["git", "tag", "--list", "v[0-9]*"], capture_output=True, text=True, check=False).stdout
    state, text = judge(os.environ.get("HOLD", ""), set(tags.split()))
    print(f"state={state}\ntext={text}")
    return 1 if state == "invalid" else 0


if __name__ == "__main__":
    sys.exit(main())
