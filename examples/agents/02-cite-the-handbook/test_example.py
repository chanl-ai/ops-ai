import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import chat_agent, chat_citations, chat_reply, folder_bindings, ops_client


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def _chat(name: str) -> dict:
    message = json.loads((FOLDER / "fixtures" / name).read_text())["message"]
    return chat_agent(ops_client(), folder_bindings(FOLDER)["agentId"], message)


def test_cited_answer_names_the_handbook_page() -> None:
    expected = json.loads((FOLDER / "expected/cited.json").read_text())
    result = _chat("question.json")
    reply = chat_reply(result)
    cites = chat_citations(result)
    blob = (reply + json.dumps(cites)).lower()
    assert bool(reply) is expected["hasReply"]
    assert bool(cites or "[" in reply) is expected["hasCitation"]
    assert any(word in blob for word in ("account opening", "document", "sole proprietor", "beneficial"))
    if cites:
        titles = " ".join(str(c.get("title") or c.get("source") or "") for c in cites if isinstance(c, dict)).lower()
        assert "document" in titles or "account" in titles


def test_missing_page_takes_the_documented_no_answer() -> None:
    expected = json.loads((FOLDER / "expected/missing.json").read_text())
    result = _chat("missing.json")
    reply = chat_reply(result).lower()
    cites = chat_citations(result)
    assert bool(chat_reply(result)) is expected["hasReply"]
    assert bool(cites) is expected["hasCitation"]
    assert expected["saysUnknown"] is True
    assert "not in the knowledge base" in reply or "do not know" in reply
