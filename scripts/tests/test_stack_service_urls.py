"""The workflow worker reaches every service agents-service reaches (scripts/stack.sh), by failure mode: a URL given
to one command and not the other, so workflow steps that need that service fail on the stack while chat, run by
agents-service, works (OPS_FILES_URL and then OPS_KB_URL went missing from the worker this way)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def urls(service: str) -> dict[str, str]:
    out = subprocess.run(
        ["bash", str(ROOT / "scripts/stack.sh"), "cmd", service], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return dict(re.findall(r"\b(OPS_[A-Z_]+_URL)=(\S+)", out))


def test_the_worker_and_agents_service_reach_the_same_services() -> None:
    api, worker = urls("agents"), urls("worker")
    assert api and api == worker, {
        "only agents-service": api.keys() - worker.keys(),
        "only the worker": worker.keys() - api.keys(),
    }


def test_an_isolated_stack_reaches_its_own_models_service_whatever_the_env_file_names(tmp_path: Path) -> None:
    """A laptop .env naming the shared stack's models-service sent every isolated run's model calls to the shared
    stack's aliases, real models included, and its fake bank certificate failed the isolated bank's TLS (c-542)."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/stack.sh").write_text((ROOT / "scripts/stack.sh").read_text())
    (tmp_path / ".env").write_text(
        "OPS_MODELS_URL=http://127.0.0.1:8730\nOPS_MODELS_FAKE_OPENAI_URL=http://127.0.0.1:8746/v1\n"
        "OPS_EGRESS_CA_FILE=/shared/.run/fake-bank/bank.crt\n"
    )
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "OPS_STACK": "isolated"}
    env |= {"OPS_MODELS_PORT": "9730", "OPS_FAKE_OPENAI_PORT": "9746"}

    def cmd(service: str) -> str:
        return subprocess.run(
            ["bash", "scripts/stack.sh", "cmd", service],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    agents, models, tools = cmd("agents"), cmd("models"), cmd("tools")
    assert "OPS_MODELS_URL=http://127.0.0.1:9730" in agents, agents
    assert "OPS_MODELS_FAKE_OPENAI_URL=http://127.0.0.1:9746/v1" in models, models
    assert f"OPS_EGRESS_CA_FILE={tmp_path}/.run/fake-bank/bank.crt" in tools, tools
