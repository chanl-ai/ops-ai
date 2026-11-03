"""Fails when the tree has more matches of a class in config/leak-patterns.txt than config/leak-baseline.txt allows.

The baseline may only fall. Commit messages and the pull request's title and body (PR_TITLE, PR_BODY) allow no match.

  python3 scripts/leak_scan.py [--base <sha>]   the tree; with --base, also the baseline and the messages since <sha>
  python3 scripts/leak_scan.py --update         lower the baseline to today's counts
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = "config/leak-patterns.txt"
BASELINE = "config/leak-baseline.txt"
# Lockfiles hold hashes that match anything; openapi.json is generated from docstrings, which are scanned instead.
SKIP = re.compile(r"(^|/)(pnpm-lock\.yaml|uv\.lock|openapi\.json)$|\.(png|jpe?g|gif|ico|webp|pdf|woff2?)$")
SELF = {PATTERNS, BASELINE, "scripts/leak_scan.py", "scripts/tests/test_leak_scan.py"}


def load_patterns(text: str) -> dict[str, re.Pattern[str]]:
    patterns: dict[str, re.Pattern[str]] = {}
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            name, regex = line.split(None, 1)
            patterns[name] = re.compile(regex.strip())
    return patterns


def load_baseline(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            name, count = line.split()
            counts[name] = int(count)
    return counts


def scan_text(text: str, patterns: dict[str, re.Pattern[str]]) -> Iterable[tuple[str, int, str]]:
    """(class, line number, line) for each line that matches a class; a line counts once per class."""
    for number, line in enumerate(text.splitlines(), 1):
        for name, pattern in patterns.items():
            if pattern.search(line):
                yield name, number, line.strip()


def scan_tree(root: Path, patterns: dict[str, re.Pattern[str]]) -> tuple[Counter[str], dict[str, list[str]]]:
    counts: Counter[str] = Counter()
    where: dict[str, list[str]] = {}
    files = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout.split(b"\0")
    for raw in files:
        path = raw.decode()
        if not path or path in SELF or SKIP.search(path) or not (root / path).is_file():
            continue
        try:
            text = (root / path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, number, line in scan_text(text, patterns):
            counts[name] += 1
            where.setdefault(path, []).append(f"{path}:{number}: [{name}] {line[:160]}")
    return counts, where


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def rises(now: Counter[str], allowed: Counter[str], names: Iterable[str]) -> list[str]:
    return [f"{n}: {now[n]} lines, baseline {allowed[n]}" for n in names if now[n] > allowed[n]]


def main(argv: list[str]) -> int:
    patterns = load_patterns((ROOT / PATTERNS).read_text())
    baseline = load_baseline((ROOT / BASELINE).read_text())
    counts, where = scan_tree(ROOT, patterns)
    if "--update" in argv:
        lowered = {n: min(counts[n], baseline[n]) for n in patterns}
        body = "".join(f"{n} {lowered[n]}\n" for n in patterns)
        (ROOT / BASELINE).write_text(
            "# Lines per class in the tree (scripts/leak_scan.py). A count may only fall.\n" + body
        )
        print("leak-scan: baseline " + ", ".join(f"{n} {lowered[n]}" for n in patterns))
        return 0
    failures = rises(counts, baseline, patterns)
    base = argv[argv.index("--base") + 1] if "--base" in argv else None
    changed: set[str] = set()
    if base:
        before = (
            load_baseline(git("show", f"{base}:{BASELINE}"))
            if BASELINE in git("ls-tree", "-r", "--name-only", base)
            else None
        )
        if before is not None:
            failures += [f"baseline raised: {r}" for r in rises(baseline, before, patterns)]
        changed = set(git("diff", "--name-only", base, "HEAD").split())
        texts = [
            (f"commit {c[:10]}", git("log", "-1", "--format=%B", c))
            for c in git("rev-list", "--no-merges", f"{base}..HEAD").split()
        ]
        texts += [
            (label, os.environ.get(var, ""))
            for label, var in (("pull request title", "PR_TITLE"), ("pull request body", "PR_BODY"))
        ]
        for label, text in texts:
            failures += [f"{label}, line {n}: [{name}] {line[:160]}" for name, n, line in scan_text(text, patterns)]
    print("leak-scan: " + ", ".join(f"{n} {counts[n]}/{baseline[n]}" for n in patterns))
    if not failures:
        lower = [n for n in patterns if counts[n] < baseline[n]]
        if lower:
            print(f"leak-scan: {', '.join(lower)} fell; lower the baseline with python3 scripts/leak_scan.py --update")
        return 0
    print("leak-scan: refused")
    for failure in failures:
        print(f"  {failure}")
    for path in sorted(changed & where.keys()):
        print("\n".join(f"  {hit}" for hit in where[path]))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
