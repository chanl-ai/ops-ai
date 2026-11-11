"""Fail when code commits change test files after the tests were committed.

Usage: python scripts/agents/tests_untouched.py <tests-commit> [<head>]

The test writer commits failing tests first; the coder may change only product code after that commit. A coder that
edits a test can make it pass without fixing the behaviour, so any test file changed in <tests-commit>..<head> is
reported and the exit code is 1. A test that is wrong goes back to the test writer through the tracker.
"""

from __future__ import annotations

import re
import subprocess
import sys

TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|e2e)/"
    r"|(^|/)test_[^/]*\.py$"
    r"|_test\.py$"
    r"|\.(test|spec)\.[cm]?[jt]sx?$"
    r"|(^|/)docs/usecases/.*/scripts/"
)


def changed_test_files(base: str, head: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}..{head}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [path for path in out.splitlines() if TEST_PATH.search(path)]


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print("usage: tests_untouched.py <tests-commit> [<head>]", file=sys.stderr)
        return 2
    base, head = argv[1], argv[2] if len(argv) == 3 else "HEAD"
    touched = changed_test_files(base, head)
    if not touched:
        print(f"tests untouched since {base}")
        return 0
    print(f"code commits after {base} changed {len(touched)} test file(s):")
    for path in touched:
        print(f"  {path}")
    print("Send a wrong test back to the test writer instead of editing it.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
