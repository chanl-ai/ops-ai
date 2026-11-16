"""A baseline may only fall: the one history check every ratchet file shares.

A check that compares the code with its baseline file cannot see the baseline being raised to match the code. This
reads the baseline files' own history instead: each commit after `began` that raises a row, adds a row or adds a file
needs a `Standards-exception: approved by <login>: <reason>` trailer, <login> being a maintainer the parent commit's
`.github/standards-maintainers.txt` lists (by hash). Used by scripts/check_portable_store.py,
scripts/check_config_literals.py and the pytest ratchets under packages/ops_store/tests and deploy/database/tests.

A checkout without the history (verify-head's one-commit export, a shallow clone) has nothing to read and reports
nothing; verify-staged and CI run it on the repository.
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
from collections import Counter
from collections.abc import Callable
from pathlib import Path

TRAILER = "Standards-exception:"
MAINTAINERS = ".github/standards-maintainers.txt"
# The one form that approves a change: a listed login, then a reason. A bare trailer, or one naming nobody listed,
# approves nothing, so a builder cannot approve its own change by writing the line.
APPROVAL = re.compile(rf"^{re.escape(TRAILER)} approved by (?P<login>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?): \S")
WANTED = f"{TRAILER} approved by <maintainer in {MAINTAINERS}>: <reason>"

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


def maintainers_at(root: Path, rev: str) -> set[str]:
    """The login hashes the maintainers file lists at `rev`; none where the commit has no such file."""
    shown = _git(root, "show", f"{rev}:{MAINTAINERS}")
    if shown.returncode:
        return set()
    return {line.strip().lower() for line in shown.stdout.splitlines() if line.strip() and not line.startswith("#")}


def login_hash(login: str) -> str:
    """How the maintainers file names a login: the repository is public, so it holds hashes, not people."""
    return hashlib.sha256(login.lower().encode()).hexdigest()


def approved(message: str, allowed: set[str]) -> bool:
    """Whether a commit message carries the approval trailer, naming a login whose hash is in `allowed`."""
    for line in message.splitlines():
        found = APPROVAL.match(line)
        if found and login_hash(found["login"]) in allowed:
            return True
    return False


def list_problems(root: Path) -> list[str]:
    """Commits after the maintainers file's first that edit it without an approval from a login the file already
    listed: without this a builder lists itself in one commit and approves its own change in the next."""
    shas = _git(root, "log", "--format=%H", "--", MAINTAINERS).stdout.split()
    return [
        f"{sha[:8]} edits {MAINTAINERS} with no {WANTED} trailer from a listed maintainer"
        for sha in shas[:-1]
        if not approved(_git(root, "log", "-1", "--format=%B", sha).stdout, maintainers_at(root, f"{sha}^"))
    ]


def problems(root: Path, began: str, pathspecs: list[str], parse: Parse = rows) -> list[str]:
    """One line for each baseline row a commit after `began` raised or added without the trailer, in files under
    `pathspecs`. A file's first commit counts as adding every row it holds."""
    if _git(root, "cat-file", "-e", f"{began}^{{commit}}").returncode:
        return []
    out: list[str] = list_problems(root)
    shas = _git(root, "log", "--format=%H", f"{began}..HEAD", "--", *pathspecs).stdout.split()
    for sha in reversed(shas):
        message = _git(root, "log", "-1", "--format=%B", sha).stdout
        if approved(message, maintainers_at(root, f"{sha}^")):
            continue
        changed = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", sha, "--", *pathspecs).stdout.split()
        for name in changed:
            before = _git(root, "show", f"{sha}^:{name}")
            after = _git(root, "show", f"{sha}:{name}")
            now = parse(after.stdout) if not after.returncode else Counter[str]()
            was = parse(before.stdout) if not before.returncode else Counter[str]()
            out += [f"{sha[:8]} raises {name}: `{row}` with no {WANTED} trailer" for row in raised(was, now)]
    return out
