"""uc-752, sdk layer: docs/usecases/agents-service/an-agent-answers-from-a-knowledge.md. A developer signed in through
the Python SDK starts a chat on the fixture knowledge and reads the cited answer (MODE: lib/main_chains.py)."""

from __future__ import annotations

from apps_walk import signed_sdk
from main_chains import says
from steps import publish_agent
from usecase_harness import check, finish, people_stack

with people_stack():
    ops = signed_sdk("builder")
    thread = ops.chat.start("ag_fraud", kb_ids=["kb_people"])
    events = list(ops.chat.say(thread["id"], "What is the daily wire limit for a personal account?"))
    kinds = [e.get("type") for e in events]
    check("1 the reply streams and ends done", kinds[:1] == ["start"] and kinds[-1:] == ["done"], kinds)
    citations = next((e["citations"] for e in events if e.get("type") == "citations"), [])
    # Non-vacuous: an agent with no knowledge cites nothing.
    plain, _ = publish_agent(ops, "Plain helper", role="Answers without documents")
    bare = ops.chat.start(plain, kb_ids=[])
    none = next((e["citations"] for e in ops.chat.say(bare["id"], "What is the daily wire limit?") if e.get("type") == "citations"), [])
    check("2 the SDK's reply cites the Wire Transfer Policy, and a chat without knowledge cites nothing",
          bool(citations) and citations[0].get("title") == "Wire Transfer Policy" and not none, (citations[:1], none))
    text = "".join(e.get("delta", "") for e in events if e.get("type") == "text")
    check("3 the answer carries the figure and its marker", says(text, "$25,000", ("limit", "wire")) and "[1]" in text, text)
    stored = ops.chat.get(thread["id"])["messages"][-1]
    check("4 the thread read back keeps the citation", bool(stored.get("citations")), stored.get("citations"))
finish()
