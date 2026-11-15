"""A baseline may only fall: the one history check every ratchet file shares.

A check that compares the code with its baseline file cannot see the baseline being raised to match the code. This
reads the baseline files' own history instead: each commit after `began` that raises a row, adds a row or adds a file
needs a `Standards-exception:` trailer a maintainer approved. Used by scripts/check_portable_store.py,
scripts/check_config_literals.py and the pytest ratchets under packages/ops_store/tests and deploy/database/tests.

A checkout without the history (verify-head's one-commit export, a shallow clone) has nothing to read and reports
nothing; verify-staged and CI run it on the repository.
"""

from __future__ import annotations

import ast
import subprocess
from collections import Counter
from collections.abc import Callable
from pathlib import Path

TRAILER = "Standards-exception:"

Parse = Callable[[str], Counter[str]]


def rows(text: str) -> Counter[str]:
    """`<count> <key>` rows, or a bare `<key>` row counted once; comment lines are skipped."""
    out: Counter[str] = Counter()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head, _, rest = line.partition(" ")
        if head.isdigit() and rest:
            out[rest.strip()] += int(head)
        else:
            out[line] += 1
    return out


def waiting_dict(name: str) -> Parse:
    """A parser for a module-level `NAME: dict[str, set[str]] = {...}` waiting list: one row for each entry."""

    def parse(text: str) -> Counter[str]:
        out: Counter[str] = Counter()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return out
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names, value = [node.target.id], node.value
            elif isinstance(node, ast.Assign):
                names, value = [t.id for t in node.targets if isinstance(t, ast.Name)], node.value
            else:
                continue
            if name not in names or not isinstance(value, ast.Dict):
                continue
            for key, entries in zip(value.keys, value.values, strict=True):
                for item in ast.walk(entries):
                    if isinstance(key, ast.Constant) and isinstance(item, ast.Constant) and isinstance(item.value, str):
                        out[f"{key.value} {item.value}"] += 1
        return out

    return parse


def raised(before: Counter[str], after: Counter[str]) -> list[str]:
    return sorted(f"{key} ({before.get(key, 0)} -> {n})" for key, n in after.items() if n > before.get(key, 0))


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def problems(root: Path, began: str, pathspecs: list[str], parse: Parse = rows) -> list[str]:
    """One line for each baseline row a commit after `began` raised or added without the trailer, in files under
    `pathspecs`. A file's first commit counts as adding every row it holds."""
    if _git(root, "cat-file", "-e", f"{began}^{{commit}}").returncode:
        return []
    out: list[str] = []
    shas = _git(root, "log", "--format=%H", f"{began}..HEAD", "--", *pathspecs).stdout.split()
    for sha in reversed(shas):
        message = _git(root, "log", "-1", "--format=%B", sha).stdout
        if any(line.startswith(TRAILER) for line in message.splitlines()):
            continue
        changed = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", sha, "--", *pathspecs).stdout.split()
        for name in changed:
            before = _git(root, "show", f"{sha}^:{name}")
            after = _git(root, "show", f"{sha}:{name}")
            now = parse(after.stdout) if not after.returncode else Counter[str]()
            was = parse(before.stdout) if not before.returncode else Counter[str]()
            out += [f"{sha[:8]} raises {name}: `{row}` with no {TRAILER} trailer" for row in raised(was, now)]
    return out
