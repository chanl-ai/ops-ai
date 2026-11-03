"""scripts/leak_scan.py end to end on a throwaway repository, one test per way a leak gets in."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("leak_scan", REPO / "scripts" / "leak_scan.py")
assert spec and spec.loader
leak_scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(leak_scan)


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def commit(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    (tmp_path / "config").mkdir()
    # Patterns written here, so a test never spells out a real word the scan hunts.
    (tmp_path / leak_scan.PATTERNS).write_text("tracker-id \\bc-\\d{2,4}\\b\nprobe-word zzprobeword\n")
    (tmp_path / "app.py").write_text("# Retries twice (c-101).\n")
    (tmp_path / leak_scan.BASELINE).write_text("tracker-id 1\n")
    git(tmp_path, "init", "-q")
    base = commit(tmp_path, "chore: start")
    monkeypatch.setattr(leak_scan, "ROOT", tmp_path)
    monkeypatch.delenv("PR_TITLE", raising=False)
    monkeypatch.delenv("PR_BODY", raising=False)
    return tmp_path, base


def test_a_clean_change_passes(repo: tuple[Path, str]) -> None:
    root, base = repo
    (root / "other.py").write_text("# Retries twice, then gives up.\n")
    commit(root, "fix: give up after two retries")
    assert leak_scan.main(["--base", base]) == 0


def test_a_new_tracker_id_in_a_comment_is_refused(repo: tuple[Path, str]) -> None:
    root, base = repo
    (root / "other.py").write_text("# Gives up after two retries (c-999).\n")
    commit(root, "fix: give up after two retries")
    assert leak_scan.main(["--base", base]) == 1


def test_raising_the_baseline_to_fit_is_refused(repo: tuple[Path, str]) -> None:
    root, base = repo
    (root / "other.py").write_text("# Gives up after two retries (c-999).\n")
    (root / leak_scan.BASELINE).write_text("tracker-id 2\n")
    commit(root, "fix: give up after two retries")
    assert leak_scan.main([]) == 0
    assert leak_scan.main(["--base", base]) == 1


def test_a_commit_message_allows_no_match(repo: tuple[Path, str]) -> None:
    root, base = repo
    (root / "other.py").write_text("# Gives up after two retries.\n")
    commit(root, "fix: give up after two retries\n\nFor c-999.")
    assert leak_scan.main(["--base", base]) == 1


def test_the_pull_request_text_allows_no_match(repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _, base = repo
    monkeypatch.setenv("PR_BODY", "Built with zzprobeword.")
    assert leak_scan.main(["--base", base]) == 1


def test_only_lockfiles_and_generated_documents_are_skipped(repo: tuple[Path, str]) -> None:
    root, _ = repo
    (root / "uv.lock").write_text('hash = "c-999"\n')
    (root / "openapi.json").write_text('{"description": "c-998"}\n')
    commit(root, "chore: lock")
    assert leak_scan.main([]) == 0
    (root / "openapi.py").write_text('"""Generated from (c-997)."""\n')
    commit(root, "chore: generate")
    assert leak_scan.main([]) == 1
