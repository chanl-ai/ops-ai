"""uc-001 chat turn with citation, api layer: docs/usecases/agents-service/chat-turn-with-citation.md."""

from __future__ import annotations

from usecase_harness import TEAM, agents, check, data, finish, sse


def _wire_limits(c: dict) -> bool:
    return c.get("title") == "Wire Transfer Policy" and "4.2 Daily limits" in c.get("section", "")


QUESTION = "What is the daily wire limit for a personal account?"

with agents() as api:
    created = api.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": ["kb_people"]}, headers=TEAM)
    check("thread created (201)", created.status_code == 201, created.text[:200])
    thread = data(created)

    res = api.post(
        f"/chat/threads/{thread['id']}/messages",
        json={"content": QUESTION},
        headers={**TEAM, "Accept": "text/event-stream"},
    )
    check("message streamed (200)", res.status_code == 200, res.text[:200])
    events = sse(res.text)
    types = [e["type"] for e in events]
    check("stream starts with start and ends with done", types[:1] == ["start"] and types[-1:] == ["done"], types)
    citations = next((e["citations"] for e in events if e["type"] == "citations"), [])
    # Non-vacuous: the citation must name the wire-limits document and section, which only kb-service's search
    # over the harness's fixture knowledge can produce.
    check(
        "citation [1] is the Wire Transfer Policy, 4.2 Daily limits",
        bool(citations) and _wire_limits(citations[0]) and citations[0]["n"] == 1,
        citations,
    )
    text = "".join(e.get("delta", "") for e in events if e["type"] == "text")
    check("answer carries the limit and its marker", "$25,000" in text and "[1]" in text, text)

    stored = data(api.get(f"/chat/threads/{thread['id']}", headers=TEAM))
    roles = [m["role"] for m in stored["messages"]]
    check("thread stores user then assistant", roles == ["user", "assistant"], roles)
    reply = stored["messages"][-1]
    check(
        "stored reply keeps the citation", bool(reply.get("citations")) and _wire_limits(reply["citations"][0]), reply
    )
    check("stored reply came from the scripted model", reply["model"].startswith("function:scripted"), reply["model"])

finish()
