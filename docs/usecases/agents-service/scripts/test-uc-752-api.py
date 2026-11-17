"""uc-752 an agent answers from a knowledge source with a citation, api layer:
docs/usecases/agents-service/an-agent-answers-from-a-knowledge.md. MODE=mock (default) is the scripted model on the
fixture knowledge; MODE=real is a real model alias on a website knowledge source (lib/main_chains.py)."""

from __future__ import annotations

from main_chains import REAL, says
from usecase_harness import agents, check, data, finish, sse

TEAM = {"X-Team-Id": "team_ops"}
QUESTION = "What is the daily wire limit for a personal account?"


def ask(api, agent: str, kb_ids: list[str]) -> dict:  # type: ignore[no-untyped-def]
    thread = data(api.post("/chat/threads", json={"agentId": agent, "kbIds": kb_ids}, headers=TEAM))
    res = api.post(
        f"/chat/threads/{thread['id']}/messages", json={"content": QUESTION}, headers={**TEAM, "Accept": "text/event-stream"}
    )
    events = sse(res.text)
    stored = data(api.get(f"/chat/threads/{thread['id']}", headers=TEAM))["messages"][-1]
    return {
        "citations": next((e["citations"] for e in events if e["type"] == "citations"), []),
        "text": "".join(e.get("delta", "") for e in events if e["type"] == "text"),
        "stored": stored,
    }


with agents() as api:
    # Non-vacuous: the same question with an agent that holds no knowledge carries no citation, so a citation below can only come
    # from kb-service's search.
    plain = data(api.post("/v1/agents", json={"name": "Plain helper", "role": "Answers without documents"}, headers=TEAM))
    api.post(f"/v1/agents/{plain['id']}/publish-requests", json={"version": plain["version"], "note": "uc-752"}, headers=TEAM)
    bare = ask(api, plain["id"], [])
    check("1 without knowledge the answer carries no citation", not bare["citations"], bare["citations"])
    cited = ask(api, "ag_fraud", ["kb_people"])
    first = (cited["citations"] or [{}])[0]
    check(
        "2 the answer cites the Wire Transfer Policy, section 4.2, as [1]",
        first.get("n") == 1 and first.get("title") == "Wire Transfer Policy" and "4.2 Daily limits" in first.get("section", ""),
        cited["citations"][:1],
    )
    check(
        "3 the answer carries the figure and its marker",
        says(cited["text"], "$25,000", ("limit", "wire")) and "[1]" in cited["text"],
        cited["text"],
    )
    reply = cited["stored"]
    check(
        "4 the stored reply keeps the citation and the model that answered",
        bool(reply.get("citations")) and reply["model"].startswith("function:scripted") != REAL,
        (reply.get("citations", [])[:1], reply["model"]),
    )
finish()
