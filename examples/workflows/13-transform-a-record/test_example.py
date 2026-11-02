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


def test_a_path_maps_and_a_missing_path_fails() -> None:
    ops = ops_client()
    assert ops.workflows.validate(YAML).ok
    made = ops.workflows.apply(YAML)
    ok = json.loads((FOLDER / "expected/ok.json").read_text())
    missing = json.loads((FOLDER / "expected/missing.json").read_text())
    run = ops.workflows.run(
        made["workflowId"], input=json.loads((FOLDER / "fixtures/valid.json").read_text()), mode="test", wait=True
    )
    assert run["status"] == ok["status"] and run["outcome"] == ok["outcome"]
    bad = ops.workflows.run(
        made["workflowId"], input=json.loads((FOLDER / "fixtures/missing.json").read_text()), mode="test", wait=True
    )
    assert bad["status"] == missing["status"] and bad["outcome"] == missing["outcome"]
