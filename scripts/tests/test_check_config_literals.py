"""The configuration-literal check, by failure mode: a new loopback fallback, literal timeout or HTTP client not seen;
one already on a member's baseline reported again; and a baseline that could be raised by rewriting it."""

from __future__ import annotations

import hashlib
import subprocess
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


def test_the_loopback_waiting_list_is_empty_and_its_last_file_is_refused_a_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert c.LOOPBACK_WAITING == {}
    # The file that waited longest: a fallback written back into it is a finding like any other.
    fastapi = tmp_path / "packages/ops_identity/src/ops_identity/fastapi.py"
    fastapi.parent.mkdir(parents=True)
    fastapi.write_text('internal = settings.platform_internal_url or "http://127.0.0.1:8711"\n')
    assert run(tmp_path, monkeypatch, "--strict") == 1
    assert "fastapi.py: 1 loopback (allowed 0)" in capsys.readouterr().err


NAMED = """
import httpx

RETRY_TIMEOUT = 30
await http.get("/a", timeout=RETRY_TIMEOUT)
await http.get("/b", timeout=defaults.HTTP_TIMEOUT)
await http.get("/c", timeout=5 * 60)
limits = httpx.Timeout(10.0, connect=3)
sync = httpx.Client(base_url=base)
fine = httpx.Timeout(settings.agents.timeout_s)
await http.get("/d", timeout=timeout)
await http.get("/e", timeout=settings.agents.timeout_s)
"""


def test_a_timeout_held_in_a_constant_or_built_by_httpx_and_a_sync_client_are_found() -> None:
    assert sorted(c.findings(NAMED)) == [
        ("client", 9),
        ("timeout", 5),
        ("timeout", 6),
        ("timeout", 7),
        ("timeout", 8),
    ]


def _git(repo: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=env).stdout.strip()


def test_a_baseline_row_raised_or_a_file_added_needs_the_trailer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = tmp_path / "services/kb-service"
    kb.mkdir(parents=True)
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github/standards-maintainers.txt").write_text(
        f"# maintainers\n{hashlib.sha256(b'owner-login').hexdigest()}\n"
    )
    (kb / c.BASELINE_NAME).write_text("# header\n2 timeout services/kb-service/src/app.py\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "the baselines begin")
    monkeypatch.setattr(c, "BASELINES_BEGAN", _git(tmp_path, "rev-parse", "HEAD"))
    (kb / c.BASELINE_NAME).write_text("# header\n1 timeout services/kb-service/src/app.py\n")
    _git(tmp_path, "commit", "-qam", "a timeout moved onto the setting")
    assert c.commit_problems(tmp_path) == []
    (kb / c.BASELINE_NAME).write_text("# header\n3 timeout services/kb-service/src/app.py\n")
    _git(tmp_path, "commit", "-qam", "a timeout back in code")
    [raised] = c.commit_problems(tmp_path)
    assert "timeout services/kb-service/src/app.py (1 -> 3)" in raised
    _git(tmp_path, "commit", "-q", "--amend", "-m", "x\n\nStandards-exception: approved by owner-login: three timeouts")
    assert c.commit_problems(tmp_path) == []
    # A member that had no file gets today's count from `--update`; that new file is a rise like any other.
    models = tmp_path / "services/models-service"
    models.mkdir()
    (models / c.BASELINE_NAME).write_text("# header\n4 client services/models-service/src/app.py\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "a baseline file for a member with none")
    [added] = c.commit_problems(tmp_path)
    assert "client services/models-service/src/app.py (0 -> 4)" in added


FORMS = """
import asyncio
import httpx as h
from httpx import AsyncClient as Pool, Timeout as Limit

DEFAULT = "http://localhost:8740"
WAIT = 30
t = 12

a = settings.kb_url or DEFAULT
b = settings.kb_url if settings.kb_url else "http://localhost:8740"
c = settings.kb_url or settings.other_url
await asyncio.wait_for(work(), 30)
await asyncio.wait_for(work(), timeout=WAIT)
await asyncio.wait_for(work(), settings.kb.timeout_s)
await http.get("/x", timeout=t)
await http.get("/x", timeout=u)
client = h.AsyncClient()
pool = Pool()
limits = Limit(5)
"""


def test_a_fallback_in_a_constant_or_a_ternary_a_named_number_and_an_aliased_client_are_found() -> None:
    assert sorted(c.findings(FORMS)) == [
        ("client", 18),
        ("client", 19),
        ("loopback", 10),
        ("loopback", 11),
        ("timeout", 14),
        ("timeout", 16),
        ("timeout", 20),
    ]


def test_a_number_in_another_function_or_a_parameter_of_the_same_name_is_not_a_timeout() -> None:
    src = (
        "def a():\n    t = 30\n    return http.get('/x', timeout=t)\n"
        "def b(t):\n    return http.get('/x', timeout=t)\n"
        "def c():\n    t = 30\n"
        "def d(t=5):\n    return http.get('/x', timeout=t)\n"
    )
    assert c.findings(src) == [("timeout", 3)]
