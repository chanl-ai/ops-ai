"""make setup (c-545), one test per failure mode in its spec: a database that is unreachable, the wrong version or
missing its row policy; a mirror that lists a package and refuses its pinned file; a model key whose base URL is wrong;
a secret in any printed line; a second run over a hand-edited value; the devcontainer's database host; and a run that
stops half-way. Live services are stood in by local HTTP servers and a patched driver call."""

from __future__ import annotations

import http.server
import os
import stat
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "deploy" / "database")]
from setup import database, mirror, model, questions  # noqa: E402
from setup.__main__ import main  # noqa: E402
from setup.report import Result  # noqa: E402
from setup.settings import write  # noqa: E402

PASSWORD = "Sup3r-secret-pw"
URL = f"postgresql://ops:{PASSWORD}@db.example.test:5432/ops"


@contextmanager
def server(routes: dict[str, tuple[int, bytes]]) -> Iterator[str]:
    """A local HTTP server answering each path with (status, body); any other path is 404."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def _answer(self) -> None:
            status, body = routes.get(self.path.split("?")[0], (404, b"{}"))
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        do_GET = do_POST = do_HEAD = _answer  # noqa: N815 - http.server's handler names

        def log_message(self, *_: Any) -> None:
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()


def inspected(version: int, present: set[str], isolated: set[str]) -> Any:
    async def fake(_url: str, ssl: bool) -> tuple[int, set[str], set[str]]:
        return version, present, isolated

    return fake


def test_a_wrong_password_or_unknown_host_fails_and_shows_no_password() -> None:
    r = database.check(f"postgresql://ops:{PASSWORD}@no-such-host.invalid:5432/ops")
    assert not r.ok and not r.settings and PASSWORD not in r.line(), r.line()


def test_a_version_outside_15_to_17_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "_inspect", inspected(140011, set(), set()))
    r = database.check(URL)
    assert not r.ok and "PostgreSQL 14, not 15 to 17" in r.reason, r.reason


def test_tenant_tables_without_their_row_policy_fail_naming_the_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "_inspect", inspected(170000, {"cases", "tenants"}, {"tenants"}))
    monkeypatch.setattr(database, "_tenant_tables", lambda: {"cases", "tenants", "runs"})
    r = database.check(URL)
    assert not r.ok and "row policy off on cases" in r.reason, r.reason


def test_an_empty_database_passes_and_its_url_is_written(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "_inspect", inspected(160004, set(), set()))
    monkeypatch.setattr(database, "_tenant_tables", lambda: {"cases"})
    r = database.check(URL)
    assert r.ok and r.settings == {"OPS_DATABASE_URL": URL} and PASSWORD not in r.line(), r.line()


def test_azure_sql_is_listed_and_not_supported_yet() -> None:
    r = database.check("mssql://sa:pw@bank.database.windows.net/ops")
    assert not r.ok and "not supported in this version" in r.reason


def test_in_the_devcontainer_our_database_is_the_postgres_side_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_INFRA", "external")
    assert "@postgres:5432/" in database.container_url()
    monkeypatch.delenv("OPS_INFRA")
    assert "@localhost:" in database.container_url()


def test_a_mirror_that_lists_a_package_and_refuses_its_pinned_file_fails_naming_it() -> None:
    pkg = next(p for p in mirror.read_uv_lock(ROOT / "uv.lock") if p.name == mirror.PYPI_PROBE)
    listing = "".join(f'<a href="/files/{f}">{f}</a>' for f in pkg.files).encode()
    with server({f"/simple/{pkg.name}/": (200, listing)}) as base:
        r = mirror.pypi(f"{base.replace('://', '://mirror-user:' + PASSWORD + '@')}/simple")
    assert not r.ok and f"{pkg.name} {pkg.version}" in r.reason and PASSWORD not in r.line(), r.line()


def test_a_second_run_keeps_a_hand_edited_value_until_the_answer_changes(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("KEEP=me\n")
    first = Result("model", True, "ok", {"DEMO_MODEL": "gpt-5-mini"}, answer="openai|gpt-5-mini")
    write(target, [first])
    target.write_text(target.read_text().replace("DEMO_MODEL=gpt-5-mini", "DEMO_MODEL=gpt-5-nano"))
    write(target, [first])
    assert "DEMO_MODEL=gpt-5-nano" in target.read_text() and "KEEP=me" in target.read_text()
    write(target, [Result("model", True, "ok", {"DEMO_MODEL": "fake"}, answer="fake")])
    text = target.read_text()
    assert "DEMO_MODEL=fake" in text and "gpt-5-nano" not in text
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_a_run_that_fails_half_way_keeps_what_passed_and_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = tmp_path / "answers.env"
    answers.write_text(
        (ROOT / "scripts/setup/answers.qa.env").read_text().replace("DATABASE=builtin", f"DATABASE={URL}")
    )
    target = tmp_path / "settings.env"
    monkeypatch.setenv("SETUP_FILE", str(target))
    monkeypatch.setattr(sys, "argv", ["setup", "--answers", str(answers)])
    monkeypatch.setattr(questions, "docker", lambda _a, needed: Result("docker", True, "stood in"))
    assert main() == 1
    out = capsys.readouterr().out
    assert "FAIL  database" in out and PASSWORD not in out
    text = target.read_text()
    assert "DEMO_MODEL=fake" in text and "OPS_DATABASE_URL" not in text


def test_an_answers_file_with_a_key_neither_tool_knows_is_refused(tmp_path: Path) -> None:
    answers = tmp_path / "answers.env"
    answers.write_text("RUNS_ON=laptop\nDATABSE=builtin\n")
    with pytest.raises(SystemExit, match="unknown key DATABSE"):
        questions.read_answers(answers)


def test_a_docker_install_gets_install_sh_answers(tmp_path: Path) -> None:
    key = "sk-test-0123456789abcdef"
    passed = [
        Result("database", True, "ok", {"OPS_DATABASE_URL": URL}),
        Result("model", True, "ok", {"DEMO_MODEL": "gpt-5-mini", "OPENAI_API_KEY": key}),
    ]
    target = tmp_path / ".env.install"
    write(target, questions.for_install(passed))
    keys = dict(line.split("=", 1) for line in target.read_text().splitlines() if "=" in line and line[0] != "#")
    assert keys == {"DATABASE": URL, "MODEL": model.OPENAI, "MODEL_NAME": "gpt-5-mini", "MODEL_API_KEY": key}
    assert set(keys) <= set(questions.INSTALL_KEYS)
    os.environ.pop("SETUP_FILE", None)


def test_in_the_devcontainer_docker_is_not_needed_in_the_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    """The workspace container has no Docker CLI; the devcontainer's compose project runs the database beside it."""
    monkeypatch.setenv("OPS_INFRA", "external")
    monkeypatch.setattr(questions, "_version", lambda _cmd: None)
    assert questions.docker("yes", needed=True).ok
    monkeypatch.delenv("OPS_INFRA")
    assert not questions.docker("yes", needed=True).ok


def test_a_valid_key_with_a_wrong_base_path_fails_and_writes_no_model(tmp_path: Path) -> None:
    key = "sk-test-0123456789abcdef"
    with server({"/openai/v1/models/gpt-4o-mini": (200, b'{"id": "gpt-4o-mini", "object": "model"}')}) as base:
        good = model.check("azure-openai", f"{base}/openai/v1", "gpt-4o-mini", key)
        bad = model.check("azure-openai", f"{base}/openai", "gpt-4o-mini", key)
    assert good.ok and good.settings["OPENAI_BASE_URL"].endswith("/openai/v1")
    assert not bad.ok and "404" in bad.reason and key not in bad.line(), bad.line()
    target = tmp_path / ".env"
    write(target, [bad])
    assert "OPENAI_API_KEY" not in target.read_text()


def test_each_reply_names_the_part_that_is_wrong_and_only_200_passes() -> None:
    """OpenAI's own replies to GET /v1/models/{id}: 200 with the model, 401 quoting part of the key, 404 naming the
    model, and a 400. Only the 200 passes; the 401 line never repeats the provider's words about the key."""
    # Split so no scanner reads it as a real project key.
    key = "sk-" + "proj-abcdef0123456789"
    quoted = f'{{"error": {{"message": "Incorrect API key provided: {key[:3]}{key[3:8]}****{key[-4:]}."}}}}'.encode()
    missing = b'{"error": {"message": "The model `gpt-5-nanno` does not exist or you do not have access to it."}}'
    routes = {
        "/v1/models/gpt-5-nano": (200, b'{"id": "gpt-5-nano", "object": "model", "owned_by": "system"}'),
        "/v1/models/gpt-5-nanno": (404, missing),
        "/v1/models/gpt-5-mini": (400, b'{"error": {"message": "bad request"}}'),
    }
    with server(routes) as base:
        ok = model.check("openai", f"{base}/v1", "gpt-5-nano", key)
        typo = model.check("openai", f"{base}/v1", "gpt-5-nanno", key)
        error = model.check("openai", f"{base}/v1", "gpt-5-mini", key)
    with server({"/v1/models/gpt-5-nano": (401, quoted)}) as base:
        refused = model.check("openai", f"{base}/v1", "gpt-5-nano", key)
    assert ok.ok and ok.settings["DEMO_MODEL"] == "gpt-5-nano" and ok.settings["OPENAI_API_KEY"] == key
    assert not typo.ok and "gpt-5-nanno" in typo.reason
    assert not error.ok and "400" in error.reason
    assert not refused.ok and "the key was refused" in refused.line() and key[-4:] not in refused.line()


def test_a_provider_error_that_quotes_the_key_never_prints_it() -> None:
    """A proxy or gateway in front of the provider may echo the request's key in its error; the line masks it."""
    key = "sk-test-echoed-0123456789"
    echoed = f'{{"error": {{"message": "bad model for key {key}"}}}}'.encode()
    with server({"/v1/models/gpt-5-mini": (400, echoed)}) as base:
        r = model.check("openai", f"{base}/v1", "gpt-5-mini", key)
    assert not r.ok and "bad model for key ***" in r.line() and key not in r.line(), r.line()
