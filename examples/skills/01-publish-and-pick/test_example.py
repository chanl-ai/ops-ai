import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import folder_bindings, ops_client, pick_skill_once


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def test_picked_skill_is_recorded_on_the_reply() -> None:
    fixture = json.loads((FOLDER / "fixtures/message.json").read_text())
    expected = json.loads((FOLDER / "expected/picked.json").read_text())
    bindings = folder_bindings(FOLDER)
    result = pick_skill_once(
        ops_client(),
        bindings["agentId"],
        fixture["message"],
        skill_id=bindings["skillId"],
        inputs=dict(fixture.get("inputs") or {}),
    )
    message = result["message"]
    skills = message.get("skills") or []
    assert bool(message.get("content") or message.get("text") or skills) is expected["hasReply"]
    assert skills, "expected the reply to list the picked skill"
    used = skills[0]
    assert used.get("how") == expected["how"]
    assert str((used.get("inputs") or {}).get("order_number")) == expected["orderNumber"]
