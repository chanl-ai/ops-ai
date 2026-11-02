import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import ops_client, send_once


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def test_send_once_returns_a_reply() -> None:
    message = json.loads((FOLDER / "fixtures/message.json").read_text())["message"]
    expected = json.loads((FOLDER / "expected/reply.json").read_text())
    result = send_once(ops_client(), message)
    assert bool(result.get("reply")) is expected["hasReply"]
