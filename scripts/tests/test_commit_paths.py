"""scripts/commit-paths.sh commits only the given paths and runs both hooks, by failure mode: a feat on
services/ with no card reaches HEAD because a private-index commit skipped commit-msg; a good commit does not land, or
lands with someone else's staged work. Each case runs the tree's script in a throwaway clone, so nothing lands here."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def clone(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", "--shared", str(ROOT), str(repo)], check=True)
    # A runner has no git identity, and a commit without one stops with exit 128.
    for key, value in (("user.name", "Commit Paths Test"), ("user.email", "commit-paths@example.test")):
        subprocess.run(["git", "config", key, value], cwd=repo, check=True)
    for name in ("commit-paths.sh", "commit-lock.sh", "commit-message-check.mjs"):
        shutil.copy2(ROOT / "scripts" / name, repo / "scripts" / name)
    for dep in (".venv", "node_modules"):
        if (ROOT / dep).exists():
            (repo / dep).symlink_to(ROOT / dep)
    return repo


def commit(repo: Path, message: str, *paths: str) -> subprocess.CompletedProcess[str]:
    (repo / "message.txt").write_text(message, encoding="utf-8")
    argv = ["bash", "scripts/commit-paths.sh", "message.txt", *paths]
    return subprocess.run(argv, cwd=repo, capture_output=True, text=True, check=False)


def head(repo: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout


def test_a_feat_on_services_with_no_card_is_refused(tmp_path: Path) -> None:
    repo = clone(tmp_path)
    before = head(repo)
    readme = repo / "services" / "tools-service" / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nA probe line.\n", encoding="utf-8")
    done = commit(repo, "feat(tools): a probe line in the readme\n", "services/tools-service/README.md")
    out = done.stdout + done.stderr
    assert done.returncode != 0 and "changelog" in out.lower(), out[-2000:]
    assert head(repo) == before, "the refused commit reached HEAD"


def test_a_scope_with_no_changed_path_under_it_is_refused(tmp_path: Path) -> None:
    repo = clone(tmp_path)
    before = head(repo)
    readme = repo / "services" / "tools-service" / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nA probe line.\n", encoding="utf-8")
    done = commit(repo, "fix(kb): a probe line in the readme\n", "services/tools-service/README.md")
    out = done.stdout + done.stderr
    assert done.returncode != 0 and "right message file" in out, out[-2000:]
    assert head(repo) == before, "the mislabelled commit reached HEAD"


def test_a_good_commit_lands_with_only_its_paths(tmp_path: Path) -> None:
    repo = clone(tmp_path)
    readme = repo / "services" / "tools-service" / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nA probe line.\n", encoding="utf-8")
    # Someone else's staged change in the shared index must not come along.
    other = repo / "docs" / "README.md"
    other.write_text(other.read_text(encoding="utf-8") + "\nNot mine.\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/README.md"], cwd=repo, check=True)
    done = commit(
        repo, "docs(tools): a probe line in the readme\n\nChangelog: readme-probe\n", "services/tools-service/README.md"
    )
    assert done.returncode == 0, (done.stdout + done.stderr)[-2000:]
    changed = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.split()
    assert changed == ["services/tools-service/README.md"], changed


def lock_repo(tmp_path: Path) -> Path:
    """A tiny repo whose pre-commit hook takes a moment, so a second commit has to wait for the first."""
    repo = tmp_path / "lock-repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / ".githooks").mkdir()
    for name in ("commit-paths.sh", "commit-lock.sh", "commit-message-check.mjs"):
        shutil.copy2(ROOT / "scripts" / name, repo / "scripts" / name)
    (repo / ".githooks" / "commit-msg").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (repo / ".githooks" / "pre-commit").write_text("#!/bin/sh\nsleep 2\n", encoding="utf-8")
    for hook in (repo / ".githooks").iterdir():
        hook.chmod(0o755)
    for cmd in (["init", "-q"], ["config", "user.name", "T"], ["config", "user.email", "t@example.test"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True)
    (repo / "seed").write_text("seed\n", encoding="utf-8")
    subprocess.run("git add -A && git commit -qm seed", shell=True, cwd=repo, check=True)
    return repo


def test_concurrent_commits_queue_and_both_land(tmp_path: Path) -> None:
    repo = lock_repo(tmp_path)
    procs = []
    for name in ("a", "b"):
        (repo / name).write_text(name, encoding="utf-8")
        (repo / f"{name}.msg").write_text(f"docs: add {name}\n", encoding="utf-8")
        argv = ["bash", "scripts/commit-paths.sh", f"{name}.msg", name]
        procs.append(subprocess.Popen(argv, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
    outs = [p.communicate() for p in procs]
    assert [p.returncode for p in procs] == [0, 0], outs
    assert "waiting for the commit lock" in "".join(e for _, e in outs)
    count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert count == "3", count


def test_a_lock_left_by_a_dead_process_is_taken_over(tmp_path: Path) -> None:
    repo = lock_repo(tmp_path)
    dead = subprocess.Popen(["true"])
    dead.wait()
    lock = repo / ".git" / "commit.lock"
    lock.mkdir()
    (lock / "pid").write_text(str(dead.pid), encoding="utf-8")
    (repo / "a").write_text("a", encoding="utf-8")
    (repo / "a.msg").write_text("docs: add a\n", encoding="utf-8")
    start = time.monotonic()
    done = subprocess.run(
        ["bash", "scripts/commit-paths.sh", "a.msg", "a"], cwd=repo, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0 and "took over" in done.stderr, done.stderr
    assert time.monotonic() - start < 20
    assert not lock.exists()
