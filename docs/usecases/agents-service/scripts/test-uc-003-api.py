"""uc-003 simple workflow through the four thread calls, api layer: docs/usecases/agents-service/simple-workflow.md."""

from __future__ import annotations

from usecase_harness import TEAM, agents, check, data, finish, new_thread, nodes, run, state

with agents() as api:
    tid = new_thread(api, "simple_workflow")
    code, events = run(api, tid, {"input": {"question": "What is the daily wire limit for a personal account?"}})
    check("run streamed (200)", code == 200, code)
    check("ran classify then answer", nodes(events) == ["classify", "answer"], nodes(events))
    s = state(api, tid)
    v = s["values"]
    check("thread finished with nothing next", s["next"] == [], s["next"])
    check("classified as a product question", v.get("category") == "product_question", v.get("category"))
    # Non-vacuous: the citation must come from retrieval over the seed knowledge, not from the graph shape.
    cites = v.get("citations") or []
    check(
        "answer cites the Wire Transfer Policy, 4.2 Daily limits",
        bool(cites) and cites[0]["title"] == "Wire Transfer Policy" and "4.2 Daily limits" in cites[0]["section"],
        cites,
    )
    check("answer is not a no-answer", v.get("no_answer") is False and "$25,000" in (v.get("answer") or ""), v)
    listed = data(api.get("/v1/threads?graph=simple_workflow", headers=TEAM))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    check("thread is listed by graph", any(r.get("threadId") == tid for r in rows), rows[:2])

finish()
