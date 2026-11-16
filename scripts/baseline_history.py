"""A baseline may only fall: the one history check every ratchet file shares.

A check that compares the code with its baseline file cannot see the baseline being raised to match the code. This
reads the baseline files' own history instead: each commit after `began` that raises a row, adds a row or adds a file
is a rise, and a rise needs an approving review on the pull request from a maintainer listed (by hash) in
`.github/standards-maintainers.txt`. The review is read from GitHub by scripts/check_review_approval.py, which sets
OPS_STANDARDS_REVIEW for the checks it runs, so nothing a commit says can approve it. Used by
scripts/check_portable_store.py, scripts/check_config_literals.py, scripts/check_typed_boundaries.py and the pytest
ratchets under packages/ops_store/tests and deploy/database/tests.

OPS_STANDARDS_REVIEW unset (a developer's machine, the checks job): a rise is printed as awaiting review and passes.
`required`: a rise fails. `approved`: a rise passes. OPS_STANDARDS_BASE narrows the history to a pull request's
commits (its base sha).

A checkout without the history (verify-head's one-commit export, a shallow clone) has nothing to read and reports
nothing; verify-staged and CI run it on the repository.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

MAINTAINERS = ".github/standards-maintainers.txt"
REVIEW_ENV = "OPS_STANDARDS_REVIEW"
BASE_ENV = "OPS_STANDARDS_BASE"
AWAITING = "awaiting maintainer review on the pull request"

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


def has_maintainers(root: Path, rev: str) -> bool:
    """Whether the commit has a maintainers file at all, however many it lists."""
    return _git(root, "cat-file", "-e", f"{rev}:{MAINTAINERS}").returncode == 0


def maintainers_at(root: Path, rev: str) -> set[str]:
    """The login hashes the maintainers file lists at `rev`; none where the commit has no such file."""
    shown = _git(root, "show", f"{rev}:{MAINTAINERS}")
    if shown.returncode:
        return set()
    return {line.strip().lower() for line in shown.stdout.splitlines() if line.strip() and not line.startswith("#")}


# The files a rise can be made in: every baseline and waiting list the history checks read.
RATCHET_PATH = re.compile(
    r"(^|/)[\w-]*baseline[\w-]*\.txt$|^access-exceptions-allowlist\.txt$|^scripts/access-baselines/"
    r"|^packages/ops_store/tests/(isolation_sites|relay_sites|loop_health)/|^deploy/database/tests/test_indexes\.py$"
    rf"|^{re.escape(MAINTAINERS)}$"
)


def rose_since(root: Path, reviewed: str, head: str = "HEAD") -> bool:
    """Whether anything between a reviewed commit and `head` raised a baseline row, added a file to one or edited a
    list that is not made of rows. A commit that is not in this checkout counts as a rise: it cannot be compared."""
    if _git(root, "cat-file", "-e", f"{reviewed}^{{commit}}").returncode:
        return True
    for name in _git(root, "diff", "--name-only", reviewed, head).stdout.split():
        if not RATCHET_PATH.search(name):
            continue
        if not name.endswith(".txt") or name == MAINTAINERS:
            return True
        before, after = _git(root, "show", f"{reviewed}:{name}"), _git(root, "show", f"{head}:{name}")
        was = rows(before.stdout) if not before.returncode else Counter[str]()
        now = rows(after.stdout) if not after.returncode else Counter[str]()
        if raised(was, now):
            return True
    return False


def login_hash(login: str) -> str:
    """How the maintainers file names a login: the repository is public, so it holds hashes, not people."""
    return hashlib.sha256(login.lower().encode()).hexdigest()


def history_start(began: str) -> str:
    """Where to read from: the pull request's base when OPS_STANDARDS_BASE names one, else `began`."""
    return os.environ.get(BASE_ENV) or began


def awaiting_review(rises: list[str]) -> list[str]:
    """What a check reports for the rises it found, by OPS_STANDARDS_REVIEW (see the module docstring)."""
    mode = os.environ.get(REVIEW_ENV, "")
    if not rises or mode == "approved":
        return []
    if mode == "required":
        return [f"{r}: {AWAITING}, from a maintainer in {MAINTAINERS}" for r in rises]
    for r in rises:
        sys.stderr.write(f"{AWAITING}: {r}\n")
    return []


def list_rises(root: Path, began: str) -> list[str]:
    """Commits that edit the maintainers file after its first: the list is a baseline too, and a login added to it is
    a rise a listed maintainer's review approves."""
    shas = _git(root, "log", "--format=%H", f"{began}..HEAD", "--", MAINTAINERS).stdout.split()
    first = _git(root, "log", "--format=%H", "--", MAINTAINERS).stdout.split()[-1:]
    return [f"{sha[:8]} edits {MAINTAINERS}" for sha in shas if sha not in first]


def rises(root: Path, began: str, pathspecs: list[str], parse: Parse = rows) -> list[str]:
    """One line for each baseline row a commit after `began` raised or added, in files under `pathspecs`. A file's
    first commit counts as adding every row it holds."""
    began = history_start(began)
    if _git(root, "cat-file", "-e", f"{began}^{{commit}}").returncode:
        return []
    out: list[str] = list_rises(root, began)
    shas = _git(root, "log", "--format=%H", f"{began}..HEAD", "--", *pathspecs).stdout.split()
    seen: set[tuple[str, str]] = set()
    for sha in reversed(shas):
        changed = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", sha, "--", *pathspecs).stdout.split()
        for name in changed:
            before = _git(root, "show", f"{sha}^:{name}")
            after = _git(root, "show", f"{sha}:{name}")
            now = parse(after.stdout) if not after.returncode else Counter[str]()
            was = parse(before.stdout) if not before.returncode else Counter[str]()
            for row in raised(was, now):
                out.append(f"{sha[:8]} raises {name}: `{row}`")
                seen.add((name, row.rsplit(" (", 1)[0]))
    return out + net_rises(root, began, pathspecs, parse, seen)


def net_rises(root: Path, began: str, pathspecs: list[str], parse: Parse, seen: set[tuple[str, str]]) -> list[str]:
    """The rows the whole branch raised: the merge base's files against HEAD's, whatever shape its commits have.
    `diff-tree` prints nothing for a merge commit, so a rise made in the merge itself is found only here. A row a commit
    already reported is not repeated."""
    base = _git(root, "merge-base", began, "HEAD").stdout.strip() or began
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    out: list[str] = []
    for name in _git(root, "diff", "--name-only", base, "HEAD", "--", *pathspecs).stdout.split():
        before = _git(root, "show", f"{base}:{name}")
        after = _git(root, "show", f"HEAD:{name}")
        now = parse(after.stdout) if not after.returncode else Counter[str]()
        was = parse(before.stdout) if not before.returncode else Counter[str]()
        out += [
            f"{head[:8]} raises {name} (net of the branch): `{row}`"
            for row in raised(was, now)
            if (name, row.rsplit(" (", 1)[0]) not in seen
        ]
    return out


def problems(root: Path, began: str, pathspecs: list[str], parse: Parse = rows) -> list[str]:
    """The rises that fail the check in this mode: none unless OPS_STANDARDS_REVIEW is `required`."""
    return awaiting_review(rises(root, began, pathspecs, parse))
