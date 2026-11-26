#!/usr/bin/env python3
"""Exit 1 when a directory (the working directory, or the one passed) is inside a checkout; 0 for an export.

  python3 scripts/in_export_only.py [dir]

A dry run is run in an export, never in a worktree: a recipe that deletes or rewrites files (a clean, a .env removal,
a reset) then has nothing of anyone's to damage. The checkouts are the paths `git worktree list` names for the
repository this script belongs to. `make review-dry-run` runs this first.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def checkouts() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "worktree", "list", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout
    return [Path(line.split(" ", 1)[1]).resolve() for line in out.splitlines() if line.startswith("worktree ")]


def main() -> int:
    where = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    for root in checkouts():
        if where == root or root in where.parents:
            print(
                f"in_export_only: {where} is inside the checkout {root}. Run a dry run in an export: "
                "git archive HEAD | tar -x -C <empty dir>",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
