import json
import sys
from pathlib import Path

import pytest
from ops_ai.errors import Forbidden

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import ROUTE_SUPPORT_MESSAGE_ID, cell_allowed, ops_as, ops_client, person_for_cell


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def _expected(name: str) -> dict:
    return json.loads((FOLDER / "expected" / name).read_text())


def _start(ops) -> dict:
    payload = json.loads((FOLDER / "fixtures" / "start.json").read_text())
    return ops.workflows.run(ROUTE_SUPPORT_MESSAGE_ID, input=payload, mode="test", wait=True)


def test_start_is_refused_without_the_cell() -> None:
    expected = _expected("refused.json")
    ops = ops_client()
    person = person_for_cell(ops, expected["area"], expected["action"], allowed=False)
    signed = ops_as(str(person["email"]))
    assert cell_allowed(signed, expected["area"], expected["action"]) is False
    with pytest.raises(Forbidden) as caught:
        _start(signed)
    err = caught.value
    assert err.status == expected["status"]
    assert err.code == expected["code"]
    details = err.details if isinstance(err.details, dict) else {}
    assert details.get("area") == expected["area"]
    assert details.get("action") == expected["action"]


def test_start_succeeds_with_the_cell() -> None:
    expected = _expected("started.json")
    cell = _expected("refused.json")
    ops = ops_client()
    person = person_for_cell(ops, cell["area"], cell["action"], allowed=True)
    signed = ops_as(str(person["email"]))
    assert cell_allowed(signed, cell["area"], cell["action"]) is True
    run = _start(signed)
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run
