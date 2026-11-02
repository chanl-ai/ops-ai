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


def test_filter_keeps_open_items() -> None:
    ops = ops_client()
    made = ops.workflows.apply(YAML)
    expected = json.loads((FOLDER / "expected/kept.json").read_text())
    run = ops.workflows.run(
        made["workflowId"], input=json.loads((FOLDER / "fixtures/items.json").read_text()), mode="test", wait=True
    )
    assert run["status"] == expected["status"]
    assert run["outcome"] == expected["outcome"]
    out = run.get("output") or {}
    assert out.get("keptCount") == expected["keptCount"]
    assert out.get("droppedCount") == expected["droppedCount"]
