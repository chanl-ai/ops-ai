#!/usr/bin/env python3
"""Git rules for the shared ops-ai tree, enforced as a Claude Code PreToolUse hook on Bash.

Several builders edit one working tree at once, so a git command that rewrites the index, the working files or the
branch for everyone loses someone else's unfinished work. This hook refuses those commands before they run and says,
in plain words, which readable command to use instead (make/git.mk). Exit 2 blocks the call; stderr is the reason.

Applies only to commands that run in the ops-ai tree (the hook's cwd, or a `cd`/`-C` into it). Rules are in RULES:
each is a pattern, the reason a person would give, and what to run instead. `python3 scripts/git-rules.py --self-test`
checks every rule against an allowed and a refused command.
"""

from __future__ import annotations

import json
import os
import re
import sys

# The shared tree is the checkout this script lives in; another repo beside it is not checked.
TREE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
COMMIT = "make commit FILES='path/one path/two' MSG='type(scope): subject' CARD=c-NNN"
# Where a command starts: the line start, after a separator or `$(`, then any VAR=value prefixes.
GIT = r"(?:^|[;&|(\n]|\$\()\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*git\s+"

RULES: list[tuple[str, str, str]] = [
    (
        r"\bgit\s+(-C\s+\S+\s+)?commit\b",
        "A plain git commit takes whatever is staged in the shared index, including other builders' files, "
        "and can skip checks.",
        f"Commit only your files: {COMMIT}",
    ),
    (
        r"\bgit\s+(-C\s+\S+\s+)?stash\b",
        "A stash takes every builder's unfinished work out of the tree.",
        "Leave the tree as it is. To compare with HEAD: git diff HEAD -- <path>",
    ),
    (
        r"\bgit\s+(-C\s+\S+\s+)?checkout\s+(\S+\s+)?--\s",
        "Checking out a file from HEAD overwrites the lines other builders have not committed yet.",
        "To drop only your own change, edit the lines back by hand. After a commit, leave shared files alone.",
    ),
    (
        r"\bgit\s+(-C\s+\S+\s+)?restore\b(?!.*--staged)(?!.*\s-S\b)",
        "Restoring a file overwrites the lines other builders have not committed yet.",
        "To unstage only: make unstage FILES='path'. To drop your own change, edit it back by hand.",
    ),
    (
        r"\bgit\s+(-C\s+\S+\s+)?reset\b.*--(hard|merge|keep)\b",
        "A hard reset throws away every builder's unfinished work.",
        "To unstage only: make unstage FILES='path'.",
    ),
    (
        r"\bgit\s+(-C\s+\S+\s+)?clean\b",
        "git clean deletes other builders' new files that are not committed yet.",
        "Delete only files you created, by name.",
    ),
    (
        r"\bgit\s+(-C\s+\S+\s+)?(switch\b|checkout\s+(-[bB]\s+)?[A-Za-z0-9._/-]+\s*($|[;&|]))",
        "Switching branches moves the ground under every builder and every running server.",
        "Stay on main. Release branches are made by scripts/ops-ai/repo.sh snapshot, from the orchestrator.",
    ),
    (
        r"\bgit\s+(-C\s+\S+\s+)?worktree\s+add\b",
        "A private worktree hides work from the shared tree, the claims and QA.",
        "Work in the shared tree; put scratch files in your session's scratchpad.",
    ),
    (
        r"\bgit\s+[^;&|\n]*--no-verify\b|(?:^|[;&|(\n])\s*NOHOOK=",
        "Skipping the hooks skips the checks that keep main green.",
        f"Fix what the check reports, then: {COMMIT}",
    ),
    (
        r"\bgit\s+(-C\s+\S+\s+)?add\s+(-A\b|--all\b|-u\b|--update\b|\.(\s|$))",
        "Staging everything stages other builders' unfinished files.",
        f"Name your files: {COMMIT}",
    ),
    (
        r"\bgit\s+(-C\s+\S+\s+)?push\b.*(\s-f\b|--force)",
        "A force push rewrites history other builders have already pulled.",
        "Ask the orchestrator; releases go through scripts/ops-ai/repo.sh.",
    ),
    (
        r"\bgit\s+(-C\s+\S+\s+)?(rebase|cherry-pick|merge)(?![-\w])",
        "Rewriting or merging history in the shared tree changes HEAD under every builder.",
        "Ask the orchestrator.",
    ),
]


def in_tree(path: str) -> bool:
    return path == TREE or path.startswith(TREE + "/")


def check(command: str, cwd: str) -> str | None:
    # Each step is checked in the folder it runs in: a `cd` moves the folder for the steps after it, and `git -C dir`
    # names its own, so a chain that commits in another repo after visiting ops-ai is not refused.
    # commit-paths.sh and the make targets run git inside themselves; only what is typed is checked. A rule matches a
    # git command where a command starts (line start, after ; & | ( or env assignments), so "git commit" quoted inside
    # a message, a heredoc or a commit body is not a command.
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
                return f"Refused in the shared ops-ai tree: {why}\nInstead: {instead}"
    return None


def self_test() -> int:
    cases = [
        ("git commit -m x", True),
        ("git -C . commit -am x", True),
        ("git stash", True),
        ("git checkout HEAD -- README.md", True),
        ("git checkout -- a.py", True),
        ("git restore a.py", True),
        ("git restore --staged a.py", False),
        ("git reset --hard", True),
        ("git reset HEAD a.py", False),
        ("git clean -fd", True),
        ("git switch main", True),
        ("git checkout -b feat/x", True),
        ("git checkout main", True),
        ("git worktree add ../wt", True),
        ("NOHOOK=1 make x", True),
        ("git add -A", True),
        ("git add .", True),
        ("git add a.py", False),
        ("git push --force", True),
        ("git rebase main", True),
        ("git merge-base --is-ancestor a HEAD", False),
        ("git merge feat/x", True),
        ("git log --oneline", False),
        ("git diff HEAD -- a.py", False),
        ("bash scripts/commit-paths.sh /tmp/m a.py", False),
        ("make commit FILES=a MSG=x", False),
        ("git status --short", False),
        ("git show HEAD:a.py", False),
        ("cd /x && git commit -m y", False),
        ("cd services/agents-service && git commit -m y", True),
        ("FOO=1 git stash", True),
        ("echo ok; git add -A", True),
        ("make commit MSG='a plain git commit lost lines' FILES=a", False),
        ("cat <<'EOF' > m\nwhy: a git checkout -- a.py wiped lines\nEOF", False),
        ("python3 - <<'EOF'\ns = 'a git stash was blocked'\nEOF", False),
    ]
    bad = [(c, want) for c, want in cases if (check(c, TREE) is not None) != want]
    for c, want in bad:
        print(f"FAIL {'refuse' if want else 'allow'}: {c}")
    hub = os.path.join(os.path.dirname(TREE), "other-repo")
    elsewhere = [
        ("git commit -m x", hub, False),
        (f"cd {TREE} && make x; cd ../other-repo && git commit -q -m y -- a", hub, False),
        (f"cd {TREE} && git stash", hub, True),
        (f"git -C {TREE} commit -m x", hub, True),
        (f"cd ../{os.path.basename(TREE)} && git add -A", hub, True),
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
