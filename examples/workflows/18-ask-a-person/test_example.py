import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import ops_client

YAML = FOLDER / "resources" / "workflow.yaml"


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def test_a_zero_deadline_times_out() -> None:
    ops = ops_client()
    made = ops.workflows.apply(YAML)
    run = ops.workflows.run(
        made["workflowId"], input=json.loads((FOLDER / "fixtures/ask.json").read_text()), mode="test", wait=True
    )
    assert run["outcome"] == json.loads((FOLDER / "expected/timeout.json").read_text())["outcome"]
