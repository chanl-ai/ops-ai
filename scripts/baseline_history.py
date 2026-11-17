"""A baseline may only fall: the one history check every ratchet file shares.

A check that compares the code with its baseline file cannot see the baseline being raised to match the code. This
reads the baseline files' own history instead: each commit after `began` that raises a row, adds a row or adds a file
is a rise, and a rise needs an approving review on the pull request from a maintainer listed (by hash) in
`.github/standards-maintainers.txt`. The review is read from GitHub by scripts/check_review_approval.py, which sets
OPS_STANDARDS_REVIEW for the checks it runs, so nothing a commit says can approve it. Used by
scripts/check_portable_store.py, scripts/check_config_literals.py, scripts/check_typed_boundaries.py and the pytest
ratchets under packages/ops_store/tests and deploy/database/tests.

OPS_STANDARDS_REVIEW says who judges a rise. `approved`: a maintainer's review exists, the rise passes. `required`: no
approval exists, the rise fails. `deferred`: this run is not the one that judges (the pre-commit hook and the `checks`
job); the rise is printed as not checked and passes, and the pull request's maintainer-review job judges it. Unset, or
any other value: the review status is unknown, so the rise fails; `make checks-history` reads the review from GitHub
and sets it. OPS_STANDARDS_BASE narrows the history to a pull request's commits (its base sha).

A checkout without the history (verify-head's one-commit export, a shallow clone) has nothing to read and reports
nothing; verify-staged and CI run it on the repository.
"""

from __future__ import annotations

import ast
import hashlib
import json
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
DEFERRED = "deferred"

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


def json_rows(text: str) -> Counter[str]:
    """A JSON baseline as rows: a number is a count for its path of keys, a list of strings is one row for each string.
    Text that does not parse is one row of its own, so breaking the file is a rise."""
    try:
        data = json.loads(text)
    except ValueError:
        return Counter({"<unparseable json>": 1})
    out: Counter[str] = Counter()

    def walk(prefix: str, node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(f"{prefix}{key} ", value)
        elif isinstance(node, list):
            for item in node:
                walk(prefix, item)
        elif isinstance(node, int) and not isinstance(node, bool):
            out[prefix.strip()] += node
        elif isinstance(node, str):
            out[f"{prefix}{node}".strip()] += 1

    walk("", data)
    return out


def parse_for(name: str) -> Parse:
    return json_rows if name.endswith(".json") else rows


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
    r"(^|/)[\w-]*baseline[\w-]*\.(txt|json)$|^access-exceptions-allowlist\.txt$|^scripts/access-baselines/"
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
        if not name.endswith((".txt", ".json")) or name == MAINTAINERS:
            return True
        parse = parse_for(name)
        before, after = _git(root, "show", f"{reviewed}:{name}"), _git(root, "show", f"{head}:{name}")
        was = parse(before.stdout) if not before.returncode else Counter[str]()
        now = parse(after.stdout) if not after.returncode else Counter[str]()
        if raised(was, now):
            return True
    return False


def login_hash(login: str) -> str:
    """How the maintainers file names a login: the repository is public, so it holds hashes, not people."""
    return hashlib.sha256(login.lower().encode()).hexdigest()


def history_start(began: str) -> str:
    """Where to read from: the pull request's base when OPS_STANDARDS_BASE names one, else `began`."""
    return os.environ.get(BASE_ENV) or began


_outcome: dict[str, int | str] = {"rises": 0, "mode": ""}


def awaiting_review(rises: list[str]) -> list[str]:
    """What a check reports for the rises it found, by OPS_STANDARDS_REVIEW (see the module docstring). Also records
    what happened, for `outcome`."""
    mode = os.environ.get(REVIEW_ENV, "")
    _outcome.update(rises=len(rises), mode=mode)
    if not rises or mode == "approved":
        return []
    if mode == DEFERRED:
        for r in rises:
            sys.stderr.write(f"not checked here, the maintainer-review job judges it: {r}\n")
        return []
    if mode == "required":
        return [f"{r}: {AWAITING}, from a maintainer in {MAINTAINERS}" for r in rises]
    return [
        f"{r}: review status unknown ({REVIEW_ENV} is not set); run make checks-history, which reads it" for r in rises
    ]


def outcome(name: str) -> str:
    """The success line after `awaiting_review` returned nothing: it says what was true, so a run that judged nothing
    never says approved."""
    n, mode = int(_outcome["rises"]), _outcome["mode"]
    if not n:
        return f"{name}: no baseline rise"
    if mode == "approved":
        return f"{name}: {n} baseline rise(s), approved by a maintainer's review on the pull request"
    return f"{name}: {n} baseline rise(s) NOT CHECKED here; the pull request's maintainer-review job judges them"


# The files that decide whether a rise passes: an edit to one could make every other rise pass, so an edit is a rise.
# CI also runs the base revision's copies of these (the maintainer-review job), so an edit here never judges itself.
PROTECTED = (
    ".github/workflows/ci.yml",
    "make/checks.mk",
    "scripts/baseline_history.py",
    "scripts/check_review_approval.py",
)


def list_rises(root: Path, began: str) -> list[str]:
    """Commits that edit the maintainers file after its first (the list is a baseline too, and a login added to it is
    a rise a listed maintainer's review approves), and any edit to a file that decides rises (PROTECTED), one by one
    and as the net effect of the branch, so a merge commit's own edit is seen too."""
    out: list[str] = []
    seen: set[str] = set()
    shas = _git(root, "log", "--format=%H", f"{began}..HEAD", "--", MAINTAINERS).stdout.split()
    first = _git(root, "log", "--format=%H", "--", MAINTAINERS).stdout.split()[-1:]
    for sha in shas:
        if sha not in first:
            out.append(f"{sha[:8]} edits {MAINTAINERS}")
            seen.add(MAINTAINERS)
    for sha in reversed(_git(root, "log", "--format=%H", f"{began}..HEAD", "--", *PROTECTED).stdout.split()):
        for name in _git(
            root, "diff-tree", "--no-commit-id", "--name-only", "-r", sha, "--", *PROTECTED
        ).stdout.split():
            out.append(f"{sha[:8]} edits {name}")
            seen.add(name)
    base = _git(root, "merge-base", began, "HEAD").stdout.strip() or began
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    for name in _git(root, "diff", "--name-only", base, "HEAD", "--", MAINTAINERS, *PROTECTED).stdout.split():
        if name in seen or (name == MAINTAINERS and not has_maintainers(root, base)):
            continue
        out.append(f"{head[:8]} edits {name} (net of the branch)")
    return out


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
    """The rises that fail the check in this mode: none only when approved, deferred or there are no rises."""
    return awaiting_review(rises(root, began, pathspecs, parse))


def judged(found: list[str]) -> list[str]:
    """For the pytest ratchets that read history: the rises `problems` found, except that a run with the review status
    absent (bare pytest on a developer's machine) skips as not checked instead of failing. A skip is never a pass; each
    run that judges sets the status: `make checks` and pre-commit defer; `make checks-history` and CI's maintainer
    review job read the review."""
    if found and REVIEW_ENV not in os.environ:  # set but empty or unknown still fails, through awaiting_review
        import pytest  # noqa: PLC0415  (only the test runs call this)

        pytest.skip(f"not checked: {len(found)} baseline rise(s) and {REVIEW_ENV} is not set; run make checks-history")
    return found
