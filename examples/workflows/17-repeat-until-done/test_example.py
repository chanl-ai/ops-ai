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


def test_repeat_hits_done_then_exhausted() -> None:
    ops = ops_client()
    made = ops.workflows.apply(YAML)
    done = ops.workflows.run(
        made["workflowId"], input=json.loads((FOLDER / "fixtures/done.json").read_text()), mode="test", wait=True
    )
    assert done["outcome"] == "done"
    stopped = ops.workflows.run(
        made["workflowId"], input=json.loads((FOLDER / "fixtures/spin.json").read_text()), mode="test", wait=True
    )
    assert stopped["outcome"] == "exhausted"
