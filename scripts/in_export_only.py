#!/usr/bin/env python3
"""Exit 1 when a directory (the working directory, or the one passed) is inside a checkout; 0 for an export.

  python3 scripts/in_export_only.py [--repo <checkout>] [dir]

A dry run is run in an export, never in a worktree: a recipe that deletes or rewrites files (a clean, a .env removal,
a reset) then has nothing of anyone's to damage. The checkouts are the paths `git worktree list` names for --repo; with
no --repo, for the repository this script sits in, else for the one `git rev-parse --git-common-dir` finds from the
working directory. A script copied into an export has neither, so it exits 2 and the caller must pass --repo.
Also refused: any directory that is, or sits under, a folder holding a .git (a separate clone), and a path that
differs from a checkout only in letter case (macOS folders ignore case).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def worktrees(repo: Path) -> list[Path] | None:
    out = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"], capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        return None
    return [Path(line.split(" ", 1)[1]) for line in out.stdout.splitlines() if line.startswith("worktree ")]


def find_checkouts(repo: str | None) -> list[Path] | None:
    candidates = [Path(repo)] if repo else [Path(__file__).resolve().parents[1], Path.cwd()]
    for candidate in candidates:
        found = worktrees(candidate)
        if found is not None:
            return found
    return None


def key(path: Path) -> str:
    return os.path.realpath(path).casefold()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("dir", nargs="?", default=".")
    a = ap.parse_args()
    roots = find_checkouts(a.repo)
    if roots is None:
        print(
            "in_export_only: cannot tell which checkouts exist; pass --repo <a checkout of the repository>",
            file=sys.stderr,
        )
        return 2
    where = Path(os.path.realpath(a.dir))
    here = key(where)
    for root in roots:
        r = key(root)
        if here == r or here.startswith(r + os.sep):
            print(
                f"in_export_only: {where} is inside the checkout {root}; use a `git archive` export",
                file=sys.stderr,
            )
            return 1
    for folder in (where, *where.parents):
        if (folder / ".git").exists():
            print(
                f"in_export_only: {folder} holds a .git, so it is a checkout; use a `git archive` export",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
