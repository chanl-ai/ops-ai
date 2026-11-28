#!/usr/bin/env python3
"""Prints `true` when a pull request changes no file against its base, else `false` (also when git cannot say). That is
the merge-back of a release that develop already holds. ci.yml's plan uses it to plan nothing; codeql.yml and
leak-scan.yml skip their scan only when their `trivial` job succeeded and printed `true`. Any other diff, a version
bump included, runs every check.

  python3 scripts/ci_trivial.py <base> <head>
  python3 scripts/ci_trivial.py --self-test
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def trivial(base: str, head: str, cwd: str | None = None) -> bool:
    """No file differs between the merge base of the two commits and head; a git failure is not trivial."""
    done = subprocess.run(
        ["git", "diff", "--quiet", "--no-renames", f"{base}...{head}"], cwd=cwd, capture_output=True, check=False
    )
    return done.returncode == 0


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", "-c", "user.name=t", "-c", "user.email=t@example.test", *args],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

        git("init", "-q", "-b", "main")
        (Path(tmp) / "version").write_text("1.0.0\n")
        git("add", "version")
        git("commit", "-q", "-m", "base")
        base = git("rev-parse", "HEAD")
        git("commit", "-q", "--allow-empty", "-m", "empty")
        same = trivial(base, "HEAD", tmp)
        (Path(tmp) / "version").write_text("1.0.1\n")
        git("commit", "-q", "-am", "version only")
        bump = trivial(base, "HEAD", tmp)
        broken = trivial("no-such-commit", "HEAD", tmp)
    cases = [("an empty commit", same, True), ("a version bump", bump, False), ("a missing base", broken, False)]
    bad = [f"{n}: got {g}, expected {w}" for n, g, w in cases if g != w]
    for b in bad:
        print(f"ci_trivial self-test FAILED: {b}")
    if not bad:
        print(f"ci_trivial self-test: {len(cases)} cases passed")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        return self_test()
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    print("true" if trivial(*argv) else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
