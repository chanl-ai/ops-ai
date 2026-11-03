#!/usr/bin/env python3
"""Git rules for ops-ai checkouts, enforced as a Claude Code PreToolUse hook on Bash.

Each person and each agent works in their own checkout: the main one (ops-ai/) or a lane worktree beside it
(ops-ai-lane-<name>/), on their own branch, and main changes only through a pull request. Branches, commits, merges
and rebases inside your own checkout are normal git. This hook refuses only what loses work or skips review: a stash
(work nobody else can see), a hard reset or clean (unpushed work gone), skipped hooks, a force push, and a push
straight to main. Exit 2 blocks the call; stderr is the reason and what to do instead.

Applies to commands that run in ops-ai or a lane (the hook's cwd, or a `cd`/`-C` into one), not in another repository
nested inside one, which follows its own rules. `python3 scripts/git-rules.py --self-test` checks every rule.
"""

from __future__ import annotations

import json
import os
import re
import sys

# The checkout this script lives in; its lane worktrees sit beside it as <name>-lane-<lane>.
TREE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
LANES = os.path.join(os.path.dirname(TREE), os.path.basename(TREE) + "-lane-")
# Where a command starts: the line start, after a separator or `$(`, then any VAR=value prefixes.
GIT = r"(?:^|[;&|(\n]|\$\()\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*git\s+"

RULES: list[tuple[str, str, str]] = [
    (
        r"\bgit\s+(-C\s+\S+\s+)?stash\b",
        "A stash hides work where no one, including the next session, will find it.",
        "Commit it to your branch (a work-in-progress commit is fine) or leave it in the tree.",
    ),
    (
        r"\bgit\s+(-C\s+\S+\s+)?reset\b.*--(hard|merge|keep)\b",
        "A hard reset throws away uncommitted and unpushed work.",
        "Commit what you want to keep first; to undo a commit, git revert it.",
    ),
    (
        r"\bgit\s+(-C\s+\S+\s+)?clean\b",
        "git clean deletes new files that are not committed yet.",
        "Delete only files you created, by name.",
    ),
    (
        r"\bgit\s+[^;&|\n]*--no-verify\b|(?:^|[;&|(\n])\s*NOHOOK=",
        "Skipping the hooks skips the checks that keep main green.",
        "Fix what the check reports, then commit or push again.",
    ),
    (
        r"\bgit\s+(-C\s+\S+\s+)?push\b.*(\s-f\b|--force)",
        "A force push rewrites history others have already pulled or reviewed.",
        "Push a new commit instead, or ask the owner.",
    ),
    (
        r"\bgit\s+(-C\s+\S+\s+)?push\b[^;&|\n]*(\s|:)main(\s|$)",
        "main changes only through a reviewed pull request.",
        "Push your branch (git push -u origin HEAD) and open a PR (gh pr create).",
    ),
]


def in_tree(path: str) -> bool:
    if not (path == TREE or path.startswith(TREE + "/") or path.startswith(LANES)):
        return False
    # A repository nested inside the checkout (its own .git below the checkout's root) follows its own rules.
    root = TREE if path == TREE or path.startswith(TREE + "/") else LANES + path[len(LANES) :].split("/", maxsplit=1)[0]
    here = path
    while len(here) > len(root):
        if os.path.exists(os.path.join(here, ".git")):
            return False
        here = os.path.dirname(here)
    return True


def check(command: str, cwd: str) -> str | None:
    # Each step is checked in the folder it runs in: a `cd` moves the folder for the steps after it, and `git -C dir`
    # names its own. A rule matches a git command where a command starts, so "git stash" quoted inside a message, a
    # heredoc or a commit body is not a command.
    here = cwd
    for step in re.split(r"&&|\|\||;|\n", command):
        moved = re.match(r"\s*cd\s+['\"]?([^'\"\s;&|]+)", step)
        if moved:
            here = os.path.normpath(os.path.join(here, os.path.expanduser(moved[1])))
            continue
        named = re.search(r"\bgit\s+-C\s+['\"]?([^'\"\s]+)", step)
        where = os.path.normpath(os.path.join(here, named[1])) if named else here
        if not in_tree(where):
            continue
        for pattern, why, instead in RULES:
            if re.search(pattern.replace(r"\bgit\s+", GIT), step, re.MULTILINE):
                return f"Refused in ops-ai: {why}\nInstead: {instead}"
    return None


def self_test() -> int:
    cases = [
        ("git stash", True),
        ("FOO=1 git stash", True),
        ("git reset --hard", True),
        ("git reset HEAD a.py", False),
        ("git clean -fd", True),
        ("NOHOOK=1 make x", True),
        ("git commit --no-verify -m x", True),
        ("git push --force", True),
        ("git push origin main", True),
        ("git push origin HEAD:main", True),
        ("git push -u origin HEAD", False),
        ("git push -u origin feat/api-own-account-run", False),
        ("git commit -m x", False),
        ("git add -A", False),
        ("git switch -c feat/x", False),
        ("git checkout main", False),
        ("git worktree add ../ops-ai-lane-x", False),
        ("git rebase origin/main", False),
        ("git merge origin/main", False),
        ("git log --oneline", False),
        ("make commit MSG='a git stash was blocked' FILES=a", False),
        ("python3 - <<'EOF'\ns = 'git push origin main'\nEOF", False),
    ]
    bad = [(c, want) for c, want in cases if (check(c, TREE) is not None) != want]
    for c, want in bad:
        print(f"FAIL {'refuse' if want else 'allow'}: {c}")
    hub = os.path.join(os.path.dirname(TREE), "other-repo")
    elsewhere = [
        ("git stash", hub, False),
        (f"cd {TREE} && git stash", hub, True),
        ("git stash", LANES + "backend", True),
        ("git stash", os.path.join(TREE, "node_modules"), True),
    ]
    for c, where, want in elsewhere:
        if (check(c, where) is not None) != want:
            print(f"FAIL {'refuse' if want else 'allow'} from {where}: {c}")
            bad.append((c, want))
    total = len(cases) + len(elsewhere)
    print(f"git-rules: {total - len(bad)} of {total} cases hold")
    return 1 if bad else 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    command = (event.get("tool_input") or {}).get("command") or ""
    reason = check(command, event.get("cwd") or "")
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
