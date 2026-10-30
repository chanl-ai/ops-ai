"""scripts/commit-paths.sh commits only the given paths and runs both hooks (c-566), by failure mode: a feat on
services/ with no card reaches HEAD because a private-index commit skipped commit-msg; a good commit does not land, or
lands with someone else's staged work. Each case runs the tree's script in a throwaway clone, so nothing lands here."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def clone(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", "--shared", str(ROOT), str(repo)], check=True)
    shutil.copy2(ROOT / "scripts" / "commit-paths.sh", repo / "scripts" / "commit-paths.sh")
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


def test_a_good_commit_lands_with_only_its_paths(tmp_path: Path) -> None:
    repo = clone(tmp_path)
    readme = repo / "services" / "tools-service" / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nA probe line.\n", encoding="utf-8")
    # Someone else's staged change in the shared index must not come along.
    other = repo / "docs" / "README.md"
    other.write_text(other.read_text(encoding="utf-8") + "\nNot mine.\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/README.md"], cwd=repo, check=True)
    done = commit(repo, "docs(tools): a probe line in the readme\n\nCard: c-566\n", "services/tools-service/README.md")
    assert done.returncode == 0, (done.stdout + done.stderr)[-2000:]
    changed = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.split()
    assert changed == ["services/tools-service/README.md"], changed
