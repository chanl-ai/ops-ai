"""The shared baseline history check, by failure mode: a raised row, a row added to a waiting list in code, and a new
file are found without the trailer and pass with it; a lowered row passes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import baseline_history as h  # pyright: ignore[reportMissingImports]


def _git(repo: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=env).stdout.strip()


def test_a_raised_row_a_new_file_and_a_new_waiting_entry_need_the_trailer(tmp_path: Path) -> None:
    sites = tmp_path / "sites"
    sites.mkdir()
    (sites / "a.txt").write_text("# header\n2 raw a.py\n")
    (tmp_path / "idx.py").write_text('WAITING: dict[str, set[str]] = {"kb": {"t.a"}}\n')
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "begin")
    began = _git(tmp_path, "rev-parse", "HEAD")
    parse = h.waiting_dict("WAITING")

    def found() -> list[str]:
        return h.problems(tmp_path, began, ["sites"]) + h.problems(tmp_path, began, ["idx.py"], parse)

    (sites / "a.txt").write_text("# header\n1 raw a.py\n")
    _git(tmp_path, "commit", "-qam", "lowered")
    assert found() == []
    (sites / "a.txt").write_text("# header\n3 raw a.py\n")
    _git(tmp_path, "commit", "-qam", "raised")
    assert any("raw a.py (1 -> 3)" in p for p in found())
    _git(tmp_path, "commit", "-q", "--amend", "-m", "raised\n\nStandards-exception: approved by a maintainer")
    assert found() == []
    (sites / "b.txt").write_text("1 raw b.py\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "a new file")
    assert any("raw b.py (0 -> 1)" in p for p in found())
    (tmp_path / "idx.py").write_text('WAITING: dict[str, set[str]] = {"kb": {"t.a", "t.b"}}\n')
    _git(tmp_path, "commit", "-qam", "a waiting entry")
    assert any("kb t.b (0 -> 1)" in p for p in found())
