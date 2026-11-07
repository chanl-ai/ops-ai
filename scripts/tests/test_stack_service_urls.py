"""The workflow worker reaches every service agents-service reaches (scripts/stack.sh), by failure mode: a URL given
to one command and not the other, so workflow steps that need that service fail on the stack while chat, run by
agents-service, works (OPS_FILES_URL and then OPS_KB_URL went missing from the worker this way)."""

from __future__ import annotations

import json
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


def test_tools_service_reaches_the_stacks_knowledge_service() -> None:
    # Without it the built-in search_knowledge answered "This tools-service searches no knowledge" on every stack.
    assert urls("tools").get("OPS_KB_URL") == urls("agents")["OPS_KB_URL"]


def test_an_offset_stack_reaches_its_own_models_service_whatever_the_env_file_names(tmp_path: Path) -> None:
    """A laptop .env naming the default stack's models-service sends an offset stack's model calls to the other
    stack's aliases, real models included, and its fake bank certificate fails the offset stack's bank TLS."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/stack.sh").write_text((ROOT / "scripts/stack.sh").read_text())
    (tmp_path / ".env").write_text(
        "OPS_MODELS_URL=http://127.0.0.1:8730\nOPS_MODELS_FAKE_OPENAI_URL=http://127.0.0.1:8746/v1\n"
        "OPS_EGRESS_CA_FILE=/shared/.run/fake-bank/bank.crt\n"
    )
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "OPS_PORT_OFFSET": "1000"}
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

    agents, models = cmd("agents"), cmd("models")
    assert "OPS_MODELS_URL=http://127.0.0.1:9730" in agents, agents
    assert "OPS_MODELS_FAKE_OPENAI_URL=http://127.0.0.1:9746/v1" in models, models
    # Before its fake bank has written a certificate, tools-service gets no CA file, so it still starts.
    assert "OPS_EGRESS_CA_FILE" not in cmd("tools")
    (tmp_path / ".run/fake-bank").mkdir(parents=True)
    (tmp_path / ".run/fake-bank/bank.crt").write_text("certificate\n")
    tools = cmd("tools")
    assert f"OPS_EGRESS_CA_FILE={tmp_path}/.run/fake-bank/bank.crt" in tools, tools


def test_kb_reaches_tools_service_for_plugin_knowledge_sources() -> None:
    """With plugins on, a plugin knowledge source is read through tools-service: kb-service without its address
    refuses the source with tools_unavailable on the stack while it works in tests."""
    assert urls("kb").get("OPS_TOOLS_URL") == urls("runner")["OPS_TOOLS_URL"]


def tools_command(root: Path, **extra: str) -> str:
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], **extra}
    return subprocess.run(
        ["bash", "scripts/stack.sh", "cmd", "tools"], cwd=root, env=env, capture_output=True, text=True, check=True
    ).stdout


def test_a_running_fake_salesforce_is_trusted_and_resolved_and_a_stopped_one_is_not(tmp_path: Path) -> None:
    """tools-service reads one CA file and one host map: the fake Salesforce failed TLS, or its names did not resolve,
    on every call unless both carry it, and a fake that has stopped must not leave a host mapped to a dead address."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/stack.sh").write_text((ROOT / "scripts/stack.sh").read_text())
    bank, fake = tmp_path / ".run/fake-bank/bank.crt", tmp_path / ".run/fake-salesforce"
    bank.parent.mkdir(parents=True)
    fake.mkdir(parents=True)
    bank.write_text("BANK\n")
    (fake / "ca.pem").write_text("SALESFORCE\n")
    hosts = json.dumps({"login.salesforce.test": "10.0.0.5:4443"})
    info = {"owner": os.getpid(), "settings": {"OPS_EGRESS_RESOLVE": hosts}}
    (fake / "info.json").write_text(json.dumps(info) + "\n")
    out = tools_command(tmp_path)
    ca = Path(re.findall(r"OPS_EGRESS_CA_FILE=(\S+)", out)[0])
    assert ca.read_text() == "BANK\nSALESFORCE\n", ca
    assert json.loads(re.findall(r"OPS_EGRESS_RESOLVE=(\S+)", out)[0])["login.salesforce.test"] == "10.0.0.5:4443"
    dead = subprocess.Popen(["true"])
    dead.wait()
    (fake / "info.json").write_text(json.dumps(info | {"owner": dead.pid}) + "\n")
    out = tools_command(tmp_path)
    assert f"OPS_EGRESS_CA_FILE={bank}" in out, out
    assert "login.salesforce.test" not in out, out


def test_a_demos_own_ca_is_trusted_beside_the_fake_banks(tmp_path: Path) -> None:
    """tools-service reads one CA file: a plugin developer's own fake system (OPS_EGRESS_EXTRA_CA in .env) failed TLS
    on every call unless its CA is bundled with the fake bank's."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/stack.sh").write_text((ROOT / "scripts/stack.sh").read_text())
    bank, extra = tmp_path / ".run/fake-bank/bank.crt", tmp_path / "extra.crt"
    bank.parent.mkdir(parents=True)
    bank.write_text("BANK\n")
    extra.write_text("EXTRA\n")
    out = tools_command(tmp_path, OPS_EGRESS_EXTRA_CA=str(extra))
    ca = Path(re.findall(r"OPS_EGRESS_CA_FILE=(\S+)", out)[0])
    assert ca.parent.parent == tmp_path and ca.read_text() == "BANK\nEXTRA\n", ca
