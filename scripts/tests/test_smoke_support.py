"""The staging smoke check's token renewal, cleanup and sweep (deploy/fly/smoke_support.mjs) run where `make
python-verify` and CI run: the cases are a node test file against a fake origin."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_smoke_support_cases_pass() -> None:
    run = subprocess.run(
        ["node", "--test", "deploy/fly/smoke_support.test.mjs"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stdout[-1500:] + run.stderr[-500:]
