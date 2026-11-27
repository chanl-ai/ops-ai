"""`make sdk-typed-proof` failure modes: unreachable env, a refused sign-in, and a green
typed smoke. Mocks only the outside world (`api_as` sign-in and HTTP); asserts through the
script's exit code and stderr. Does not touch the shared stack database."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
CLEAN = {k: v for k, v in os.environ.items() if not k.startswith(("OPS_", "MAKE", "PYTEST_CURRENT_TEST", "STACK_"))}


@pytest.fixture()
def proof(monkeypatch: pytest.MonkeyPatch):
    sys.path.insert(0, str(SCRIPTS))
    import sdk_typed_proof as mod  # noqa: PLC0415

    monkeypatch.setattr(mod, "addresses", lambda _env: {"platform": "https://ops.test"})
    return mod


def test_unreachable_local_exits_2_with_make_up_hint(
    proof: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(proof, "token", boom)

    assert proof.main([]) == 2
    err = capsys.readouterr().err
    assert "cannot reach local" in err and "make up && make health" in err


def test_unreachable_staging_exits_2_with_stg_hint(
    proof: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(proof, "token", boom)

    assert proof.main(["--env", "staging"]) == 2
    err = capsys.readouterr().err
    assert "cannot reach staging" in err and "STG_APP" in err


def test_refused_sign_in_exits_2_with_message(
    proof: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from api_as import Refused  # noqa: PLC0415

    def boom(*_a: Any, **_k: Any) -> Any:
        raise Refused("api: missing role")

    monkeypatch.setattr(proof, "token", boom)

    assert proof.main(["--as", "builder"]) == 2
    assert "api: missing role" in capsys.readouterr().err


def test_ok_lists_agents_and_prints_env(
    proof: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(proof, "token", lambda *_a, **_k: {"token": "t", "team": "team_a"})

    ops = MagicMock()
    ops.agents.list.return_value = iter([{"id": "ag_1", "name": "Desk"}])
    ops.raw.platform.me_me.return_value = {"email": "builder@example.com"}
    ops.__enter__.return_value = ops
    ops.__exit__.return_value = None
    monkeypatch.setattr(proof, "OpsAI", lambda **_kw: ops)

    assert proof.main(["--as", "builder", "--env", "local"]) == 0
    out = capsys.readouterr().out
    assert "sdk-typed-proof: ok" in out
    assert "env=local" in out and "as=builder" in out
    assert "agents=1" in out and "builder@example.com" in out


def test_make_sdk_typed_proof_defaults_as_to_builder() -> None:
    """Without AS= on the command line, the target must not inherit admin from dev.mk."""
    dry = subprocess.run(
        ["make", "--no-print-directory", "-n", "sdk-typed-proof"],
        cwd=ROOT,
        env=CLEAN,
        capture_output=True,
        text=True,
        check=False,
    )
    assert dry.returncode == 0, dry.stderr
    assert "--as 'builder'" in dry.stdout
    assert "--env local" in dry.stdout

    with_as = subprocess.run(
        ["make", "--no-print-directory", "-n", "sdk-typed-proof", "AS=viewer", "ENV=staging"],
        cwd=ROOT,
        env=CLEAN,
        capture_output=True,
        text=True,
        check=False,
    )
    assert with_as.returncode == 0, with_as.stderr
    assert "--as 'viewer'" in with_as.stdout
    assert "--env staging" in with_as.stdout
