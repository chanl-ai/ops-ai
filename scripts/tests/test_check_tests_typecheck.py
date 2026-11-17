"""The test-file type error baseline, by failure mode: an error in product code let through, a test file above its row
or new to the baseline let through, `--update` or `--seed` raising an allowance, and a rise in a commit not seen."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import baseline_history as h  # pyright: ignore[reportMissingImports]
import check_tests_typecheck as c  # pyright: ignore[reportMissingImports]

BAD = 'x: int = "no"\n'


def project(tmp_path: Path) -> Path:
    p = tmp_path / "services/demo"
    for d in ("src", "tests"):
        (p / d).mkdir(parents=True)
    (p / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0"\n[tool.pyright]\ntypeCheckingMode = "strict"\n'
    )
    (p / "src/app.py").write_text("y: int = 1\n")
    (p / "tests/test_a.py").write_text(BAD * 2)
    return p


def run(p: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *flags: str) -> tuple[int, str]:
    monkeypatch.chdir(p)
    code = c.main([*flags, "src", "tests"])
    out = capsys.readouterr()
    return code, out.out + out.err


def test_real_pyright_holds_tests_to_the_baseline_and_src_to_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    p = project(tmp_path)
    code, out = run(p, monkeypatch, capsys)
    assert code == 1 and "tests/test_a.py: 2 type errors, 0 allowed" in out  # no file: zero allowed
    assert run(p, monkeypatch, capsys, "--seed")[0] == 0
    assert (p / c.BASELINE_NAME).read_text().endswith("2 tests/test_a.py\n")
    assert run(p, monkeypatch, capsys)[0] == 0
    (p / "tests/test_a.py").write_text(BAD * 3)
    (p / "tests/test_b.py").write_text(BAD)
    code, out = run(p, monkeypatch, capsys)
    assert code == 1 and "test_a.py: 3 type errors, 2 allowed" in out and "test_b.py: 1 type errors, 0 allowed" in out
    (p / "tests/test_a.py").write_text(BAD)
    (p / "tests/test_b.py").unlink()
    (p / "src/app.py").write_text(BAD)
    code, out = run(p, monkeypatch, capsys)
    assert code == 1 and "src/app.py:1:" in out


def test_update_only_lowers_and_seed_refuses_an_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    p = project(tmp_path)
    c.write_baseline(p / c.BASELINE_NAME, c.Counter({"tests/test_a.py": 1, "tests/test_gone.py": 4}))
    (p / "tests/test_b.py").write_text(BAD)
    assert run(p, monkeypatch, capsys, "--update")[0] == 1  # test_a is above its row and test_b has none
    assert h.rows((p / c.BASELINE_NAME).read_text()) == c.Counter({"tests/test_a.py": 1})
    assert run(p, monkeypatch, capsys, "--seed")[0] == 1
    assert h.rows((p / c.BASELINE_NAME).read_text()) == c.Counter({"tests/test_a.py": 1})


def test_a_commit_that_adds_or_raises_a_row_is_a_rise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(k)
    monkeypatch.setenv(h.REVIEW_ENV, "required")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True, env=env).stdout

    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "begin")
    began = git("rev-parse", "HEAD").strip()
    f = tmp_path / "services/demo" / c.BASELINE_NAME
    f.parent.mkdir(parents=True)
    f.write_text(c.HEADER + "2 tests/test_a.py\n")
    git("add", ".")
    git("commit", "-qm", "seed")
    assert any("raises" in r for r in h.problems(tmp_path, began, c.PATHSPECS))
    began = git("rev-parse", "HEAD").strip()
    f.write_text(c.HEADER + "1 tests/test_a.py\n")
    git("commit", "-qam", "lower")
    assert h.problems(tmp_path, began, c.PATHSPECS) == []
    f.write_text(c.HEADER + "3 tests/test_a.py\n")
    git("commit", "-qam", "raise")
    assert any("raises" in r for r in h.problems(tmp_path, began, c.PATHSPECS))


def test_only_a_tests_folder_directly_under_the_project_is_a_test_file(tmp_path: Path) -> None:
    p = project(tmp_path)
    assert c.test_key(p / "tests/sub/test_b.py") == (p, "tests/sub/test_b.py")
    assert c.test_key(p / "src/pkg/tests/helper.py") is None
