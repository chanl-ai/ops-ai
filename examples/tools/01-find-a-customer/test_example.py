import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import customer_emails, find_customer, ops_client


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def test_read_tool_returns_the_customer() -> None:
    wanted = json.loads((FOLDER / "fixtures/input.json").read_text())["email"]
    expected = json.loads((FOLDER / "expected/customer.json").read_text())["email"]
    result = find_customer(ops_client(), wanted)
    assert wanted in customer_emails(result)
    assert expected in customer_emails(result)
