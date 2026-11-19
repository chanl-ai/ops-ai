import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
from test_audit import changed_lines


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_a_deleted_file_is_skipped_and_the_kept_files_are_still_scored(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "gone.py").write_text("a = 1\nb = 2\n")
    (tmp_path / "kept.py").write_text("x = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "rm", "-q", "gone.py")
    (tmp_path / "kept.py").write_text("x = 1\ny = 2\n")
    _git(tmp_path, "commit", "-qam", "change")
    assert changed_lines(tmp_path, "HEAD~1", None) == {"kept.py": {2}}
