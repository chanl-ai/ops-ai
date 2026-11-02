import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import ops_client, search_page


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def test_search_returns_a_passage() -> None:
    query = json.loads((FOLDER / "fixtures/query.json").read_text())
    expected = json.loads((FOLDER / "expected/passage.json").read_text())
    result = search_page(ops_client(), query["question"], limit=int(query.get("limit") or 3))
    assert bool(result.get("passages")) is expected["hasPassage"]
