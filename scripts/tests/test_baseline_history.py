"""The shared baseline history check, by failure mode: a raised row, a row added to a waiting list in code, a new file
and an edit of the maintainers list are rises; a rise fails only where the pull request's review is required, passes
once a listed maintainer approved it, and is only printed on a developer's machine; a lowered row is no rise."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import baseline_history as h  # pyright: ignore[reportMissingImports]


def _git(repo: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=env).stdout.strip()


def _repo(tmp_path: Path) -> str:
    sites = tmp_path / "sites"
    sites.mkdir()
    (sites / "a.txt").write_text("# header\n2 raw a.py\n")
    (tmp_path / "idx.py").write_text('WAITING: dict[str, set[str]] = {"kb": {"t.a"}}\n')
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github/standards-maintainers.txt").write_text(f"# who\n{hashlib.sha256(b'owner').hexdigest()}\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "begin")
    return _git(tmp_path, "rev-parse", "HEAD")


def test_a_raised_row_a_new_file_and_a_new_waiting_entry_are_rises_that_need_the_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    began = _repo(tmp_path)
    monkeypatch.setenv(h.REVIEW_ENV, "required")
    parse = h.waiting_dict("WAITING")

    def found() -> list[str]:
        return h.problems(tmp_path, began, ["sites"]) + h.problems(tmp_path, began, ["idx.py"], parse)

    (tmp_path / "sites/a.txt").write_text("# header\n1 raw a.py\n")
    _git(tmp_path, "commit", "-qam", "lowered")
    assert found() == []
    (tmp_path / "sites/a.txt").write_text("# header\n3 raw a.py\n")
    _git(tmp_path, "commit", "-qam", "raised")
    assert any("raw a.py (1 -> 3)" in p for p in found())
    (tmp_path / "sites/b.txt").write_text("1 raw b.py\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "a new file")
    assert any("raw b.py (0 -> 1)" in p for p in found())
    (tmp_path / "idx.py").write_text('WAITING: dict[str, set[str]] = {"kb": {"t.a", "t.b"}}\n')
    _git(tmp_path, "commit", "-qam", "a waiting entry")
    assert any("kb t.b (0 -> 1)" in p for p in found())


def test_a_rise_fails_only_where_the_review_is_required_and_passes_once_approved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing a commit says approves it, so a trailer a builder wrote itself changes nothing."""
    began = _repo(tmp_path)
    (tmp_path / "sites/a.txt").write_text("# header\n9 raw a.py\n")
    _git(tmp_path, "commit", "-qam", "raised\n\nStandards-exception: approved by owner: my own line")
    for mode, red in (("required", True), ("approved", False), ("", False)):
        monkeypatch.setenv(h.REVIEW_ENV, mode)
        assert bool(h.problems(tmp_path, began, ["sites"])) is red, mode
    assert "awaiting maintainer review on the pull request" in capsys.readouterr().err
    # The pull request's base narrows the history to its own commits.
    monkeypatch.setenv(h.REVIEW_ENV, "required")
    monkeypatch.setenv(h.BASE_ENV, _git(tmp_path, "rev-parse", "HEAD"))
    assert h.problems(tmp_path, began, ["sites"]) == []


def test_editing_the_maintainers_list_is_a_rise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    began = _repo(tmp_path)
    monkeypatch.setenv(h.REVIEW_ENV, "required")
    (tmp_path / ".github/standards-maintainers.txt").write_text(f"{h.login_hash('owner')}\n{h.login_hash('me')}\n")
    _git(tmp_path, "commit", "-qam", "list myself")
    assert any("standards-maintainers.txt" in p for p in h.problems(tmp_path, began, ["sites"]))


def test_a_rise_made_inside_a_merge_commit_is_found_from_the_net_effect_of_the_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`diff-tree` prints nothing for a merge commit, so a row raised and a file added in the merge itself gave no rise.
    The base's tree against the head's does not depend on how the commits are shaped."""
    began = _repo(tmp_path)
    main = _git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD")
    _git(tmp_path, "checkout", "-q", "-b", "side")
    (tmp_path / "other.txt").write_text("side\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "side work")
    _git(tmp_path, "checkout", "-q", main)
    (tmp_path / "other2.txt").write_text("main\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "main work")
    _git(tmp_path, "merge", "-q", "--no-commit", "--no-ff", "side")
    (tmp_path / "sites/a.txt").write_text("# header\n9 raw a.py\n")
    (tmp_path / "sites/b.txt").write_text("1 raw b.py\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "merge side")
    monkeypatch.setenv(h.REVIEW_ENV, "required")
    found = h.problems(tmp_path, began, ["sites"])
    assert any("raw a.py (2 -> 9)" in p for p in found), found
    assert any("raw b.py (0 -> 1)" in p for p in found), found
    monkeypatch.setenv(h.REVIEW_ENV, "approved")
    assert h.problems(tmp_path, began, ["sites"]) == []
