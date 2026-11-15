"""The configuration-literal check, by failure mode: a new loopback fallback, literal timeout or HTTP client not seen;
one already on a member's baseline reported again; and a baseline that could be raised by rewriting it."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_config_literals as c  # pyright: ignore[reportMissingImports]

CODE = '''
"""Mentions http://127.0.0.1:8700 and timeout=5 in a docstring only."""
import httpx

base = settings.agents_url or f"http://127.0.0.1:{settings.port}"
other = settings.kb_url or "http://localhost:8740"
http = httpx.AsyncClient(base_url=base, timeout=5)
await http.get("/health", timeout=2.5)
domain = sender.rpartition("@")[2] or "localhost"
await http.get("/health", timeout=settings.agents.timeout_s)
'''


def repo(tmp_path: Path, source: str = CODE) -> Path:
    src = tmp_path / "services" / "kb-service" / "src" / "ops_kb"
    src.mkdir(parents=True)
    (src / "app.py").write_text(source)
    return tmp_path


def run(root: Path, monkeypatch: pytest.MonkeyPatch, *flags: str) -> int:
    monkeypatch.setattr(sys, "argv", ["check_config_literals.py", *flags])
    return c.main(root)


def test_each_literal_is_found_and_text_that_only_mentions_one_is_not() -> None:
    assert sorted(c.findings(CODE)) == [
        ("client", 7),
        ("loopback", 5),
        ("loopback", 6),
        ("timeout", 7),
        ("timeout", 8),
    ]


def test_a_new_site_fails_and_one_on_the_baseline_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clean = CODE.replace(' or f"http://127.0.0.1:{settings.port}"', "").replace(' or "http://localhost:8740"', "")
    root = repo(tmp_path, clean)
    assert run(root, monkeypatch, "--strict") == 1
    assert run(root, monkeypatch, "--update") == 0
    assert run(root, monkeypatch, "--strict") == 0
    app = root / "services/kb-service/src/ops_kb/app.py"
    app.write_text(clean + 'await http.get("/x", timeout=30)\n')
    capsys.readouterr()
    assert run(root, monkeypatch, "--strict") == 1
    assert "app.py: 3 timeout (allowed 2)" in capsys.readouterr().err


def test_a_loopback_fallback_fails_whatever_the_baseline_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path)
    baseline = root / "services/kb-service" / c.BASELINE_NAME
    baseline.write_text("2 loopback services/kb-service/src/ops_kb/app.py\n")
    run(root, monkeypatch, "--update")
    assert "loopback" not in baseline.read_text()
    assert run(root, monkeypatch, "--strict") == 1
    assert "app.py: 2 loopback (allowed 0)" in capsys.readouterr().err


def test_update_lowers_a_row_and_never_raises_or_adds_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repo(tmp_path)
    baseline = root / "services/kb-service" / c.BASELINE_NAME
    baseline.write_text("5 timeout services/kb-service/src/ops_kb/app.py\n")
    run(root, monkeypatch, "--update")
    # The two timeouts fell from five; the client was never on the file, so it stays a finding.
    assert c.read_baseline(baseline.read_text()) == {("timeout", "services/kb-service/src/ops_kb/app.py"): 2}
    assert run(root, monkeypatch, "--strict") == 1


def test_the_loopback_waiting_list_holds_one_file_and_fails_once_its_fallback_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert c.LOOPBACK_WAITING == {"packages/ops_identity/src/ops_identity/fastapi.py": 1}
    # A tree where that file has no fallback left: the entry itself is the finding.
    waiting = tmp_path / next(iter(c.LOOPBACK_WAITING))
    waiting.parent.mkdir(parents=True)
    waiting.write_text("internal = settings.endpoint('platform_internal').base\n")
    assert run(tmp_path, monkeypatch, "--strict") == 1
    assert "fastapi.py: its loopback fallback is gone" in capsys.readouterr().err
