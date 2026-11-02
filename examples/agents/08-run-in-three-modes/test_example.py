import json
import sys
import time
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


def test_one_agent_starts_in_stream_wait_and_background() -> None:
    ops = ops_client()
    agent_id = folder_bindings(FOLDER)["agentId"]
    message = json.loads((FOLDER / "fixtures/question.json").read_text())["message"]
    expected = json.loads((FOLDER / "expected/reply.json").read_text())
    waited = ops.agents.run(agent_id, message, mode="wait")
    streamed = ops.agents.run(agent_id, message, mode="stream")
    background = ops.agents.run(agent_id, message, mode="background")
    assert bool(waited.get("reply")) is expected["hasReply"]
    assert waited.get("runId") and waited.get("threadId")
    assert bool(streamed.get("chunks") or streamed.get("reply")) is expected["hasChunks"]
    assert background.get("runId") and background.get("threadId")
    deadline = time.monotonic() + 20
    state: dict = {}
    while time.monotonic() < deadline:
        state = ops.raw.agents.threads_thread_state(background["threadId"])
        values = state.get("values") or state.get("state") or state
        if isinstance(values, dict) and (values.get("reply") or state.get("reply")):
            break
        time.sleep(0.4)
    blob = json.dumps(state)
    assert "reply" in blob or background["runId"] in blob
