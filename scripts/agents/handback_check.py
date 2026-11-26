"""A builder's last step: pass only once its branch is pushed and its worktree and preview are gone.

make agent-handback-check BRANCH=feat/x  (run from the main checkout, after `git worktree remove`).

A worktree left behind holds a checkout, node_modules and often a running stack; dozens of them filled the disk and
the port range. The check fails while any of these is true, naming the fix:
- a worktree still has BRANCH checked out (dirty, unpushed, or clean and pushed and only waiting to be removed);
- BRANCH is not on origin, or the local branch has commits origin lacks;
- a preview stack started for BRANCH is still running (its console pid in <main>/.run/previews is alive).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def worktree_for(repo: Path, branch: str) -> Path | None:
    path = None
    for line in git(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree ") :])
        elif line == f"branch refs/heads/{branch}" and path is not None:
            return path
    return None


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return pid > 0


def running_preview(main: Path, branch: str) -> int | None:
    """The offset of a live preview started for the branch, from the registry scripts/preview.py keeps."""
    reg = main / ".run" / "previews"
    for f in sorted(reg.glob("*.json")) if reg.is_dir() else []:
        try:
            e = json.loads(f.read_text())
            if e.get("branch") != branch:
                continue
            pid = int((main / ".run" / f"offset-{e['offset']}" / "console.pid").read_text().strip())
        except (OSError, ValueError, KeyError):
            continue
        if alive(pid):
            return int(e["offset"])
    return None


def check(repo: Path, branch: str, remote: str = "origin") -> tuple[bool, str]:
    main = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir") or repo / ".git").parent
    remote_sha = git(repo, "ls-remote", remote, f"refs/heads/{branch}").split("\t")[0]
    local_sha = git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
    wt = worktree_for(repo, branch)
    if wt is not None:
        if git(wt, "status", "--porcelain"):
            return False, f"{wt} has uncommitted files: commit or drop them, push, then git worktree remove {wt}"
        if git(wt, "rev-parse", "HEAD") != remote_sha:
            return False, f"{branch} is not pushed at its head: git push, then git worktree remove {wt}"
        return (
            False,
            f"{wt} is clean and pushed but still there: make wt-stop BRANCH={branch}, git worktree remove {wt}",
        )
    if not remote_sha:
        return False, f"{branch} is not on {remote}: push it before handing back"
    if local_sha and local_sha != remote_sha:
        return False, f"local {branch} is at {local_sha[:9]}, {remote} at {remote_sha[:9]}: push the local commits"
    offset = running_preview(main, branch)
    if offset is not None:
        return False, (
            f"the preview for {branch} still runs at offset {offset}, and make wt-stop needs the worktree it ran from: "
            f"git worktree add <path> {branch}, make wt-stop BRANCH={branch}, then git worktree remove <path>"
        )
    return True, f"{branch} pushed at {remote_sha[:9]}; worktree and preview gone"


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--branch", required=True)
    ap.add_argument("--repo", default=".", help="any checkout of the repository (default: here)")
    ap.add_argument("--remote", default="origin")
    a = ap.parse_args()
    ok, line = check(Path(a.repo).resolve(), a.branch, a.remote)
    print(("ok: " if ok else "handback-check: ") + line)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
