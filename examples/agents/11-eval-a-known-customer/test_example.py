import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import folder_bindings, ops_client


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def test_eval_scores_a3_cases_without_a_local_runner() -> None:
    expected = json.loads((FOLDER / "expected/summary.json").read_text())
    cases = json.loads((FOLDER / "fixtures/cases.json").read_text())
    result = ops_client().agents.eval(folder_bindings(FOLDER)["agentId"], cases)
    assert result["summary"]["total"] == expected["total"]
    assert result["summary"]["passed"] == expected["passed"]
    assert result["summary"]["regressions"] == expected["regressions"]
    by_name = {row["caseName"]: row for row in result["results"]}
    assert by_name["known-customer"]["draft"]["status"] == "pass"
    assert by_name["missing-customer"]["draft"]["status"] == "pass"
    assert by_name["write-refused"]["draft"]["status"] == "pass"
    assert by_name[expected["failingCase"]]["draft"]["status"] == "fail"
    assert by_name[expected["failingCase"]]["live"] is None
    assert by_name[expected["failingCase"]]["regression"] is False
