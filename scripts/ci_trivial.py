#!/usr/bin/env python3
"""Prints `true` when the diff between two commits holds nothing to test, else `false`: no file at all (a merge-back
of a release that develop already holds), or only the release's version fields (deploy/release/version, the one
`version` line of each SDK's package file and of its entry in uv.lock) and the folded changelog (changelog/**). The
decision reads the diff, never a branch name, so a branch that carries any other change is tested in full. ci.yml's
plan step uses it for a pull request and a merge queue group; codeql.yml and leak-scan.yml skip their jobs on it.

  python3 scripts/ci_trivial.py <base> <head>
  python3 scripts/ci_trivial.py --self-test
"""

from __future__ import annotations

import re
import subprocess
import sys

# Per file, the changed lines that count as the version field. uv.lock also needs the hunk to sit in the ops-ai entry.
VERSION_LINES = {
    "sdk/typescript/package.json": re.compile(r'^\s*"version": "[^"]*",?$'),
    "sdk/python/pyproject.toml": re.compile(r'^version = "[^"]*"$'),
    "sdk/python/src/ops_ai/__init__.py": re.compile(r'^__version__ = "[^"]*"$'),
    "uv.lock": re.compile(r'^version = "[^"]*"$'),
}
WHOLE = ("deploy/release/version",)
FOLDED = re.compile(r"^changelog/.*\.json$")


def only_version_lines(path: str, diff: str) -> bool:
    pattern = VERSION_LINES[path]
    changed = [ln for ln in diff.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    if not changed or not all(pattern.match(ln[1:]) for ln in changed):
        return False
    return path != "uv.lock" or 'name = "ops-ai"' in diff


def trivial(diffs: dict[str, str]) -> bool:
    """`diffs` maps each changed path to its unified diff (-U2)."""
    for path, diff in diffs.items():
        if path in WHOLE or FOLDED.match(path):
            continue
        if path in VERSION_LINES and only_version_lines(path, diff):
            continue
        return False
    return True


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def read(base: str, head: str) -> dict[str, str]:
    """Each changed path with its diff (only the files with a version field need one)."""
    paths = [p for p in git("diff", "--name-only", f"{base}...{head}").splitlines() if p]
    return {p: git("diff", "-U2", f"{base}...{head}", "--", p) if p in VERSION_LINES else "" for p in paths}


def self_test() -> int:
    lock = ' name = "ops-ai"\n-version = "1.0.0"\n+version = "1.2.1"\n source = x\n'
    other = ' name = "requests"\n-version = "1.0.0"\n+version = "1.2.1"\n'
    ts = '-  "version": "1.0.0",\n+  "version": "1.2.1",\n'
    cases = [
        ("no file is trivial", trivial({}), True),
        ("the version file alone", trivial({"deploy/release/version": ""}), True),
        (
            "the version fields and the folded changelog",
            trivial(
                {
                    "deploy/release/version": "",
                    "changelog/releases/1.2.1.json": "",
                    "sdk/typescript/package.json": ts,
                    "uv.lock": lock,
                }
            ),
            True,
        ),
        ("another dependency's version in uv.lock", trivial({"uv.lock": other}), False),
        ("a code file next to the version", trivial({"deploy/release/version": "", "services/a/x.py": ""}), False),
        (
            "a package.json change beyond the version",
            trivial({"sdk/typescript/package.json": ts + '+  "name": "y",\n'}),
            False,
        ),
        ("a branch named release/x is no excuse", trivial({"docs/a.md": ""}), False),
    ]
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
    print("true" if trivial(read(*argv)) else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
