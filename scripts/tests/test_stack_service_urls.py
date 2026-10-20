"""The workflow worker reaches every service agents-service reaches (scripts/stack.sh), by failure mode: a URL given
to one command and not the other, so workflow steps that need that service fail on the stack while chat, run by
agents-service, works (OPS_FILES_URL and then OPS_KB_URL went missing from the worker this way)."""

from __future__ import annotations

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
