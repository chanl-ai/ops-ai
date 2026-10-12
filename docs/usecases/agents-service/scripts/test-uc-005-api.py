"""uc-005 a pause survives a restart, api layer: docs/usecases/agents-service/pause-survives-restart.md."""

from __future__ import annotations

from usecase_harness import EMAILS, agents, check, data, finish, new_thread, run, state

with agents() as api:
    tid = new_thread(api, "complex_workflow")
    code, events = run(api, tid, {"input": {"email": EMAILS[1]}})
    check(
        "first process paused the run for review",
        code == 200 and events[-1]["data"]["status"] == "interrupted",
        events[-1:],
    )
    before = state(api, tid)
    review_id = (before.get("interrupt") or {}).get("payload", {}).get("review_id")
    check("review id recorded before the restart", bool(review_id), before.get("interrupt"))

# The first process has exited here; a fresh process opens a new pool and compiles the graphs again.
with agents() as api:
    after = state(api, tid)
    # Non-vacuous: the second process holds nothing in memory, so this interrupt can only come from PostgreSQL.
    shown = (after.get("interrupt") or {}).get("payload", {})
    check(
        "new process sees the same review", shown.get("kind") == "review" and shown.get("review_id") == review_id, shown
    )
    decided = api.post(f"/reviews/{tid}/decision", json={"decision": "approved"})
    check("decided in the new process (200)", decided.status_code == 200, decided.text[:200])
    last = data(api.get(f"/v1/threads/{tid}/runs"))[-1]
    check("reply sent once after the restart", last["nodes"].count("send_reply") == 1, last["nodes"])
    v = state(api, tid)["values"]
    check("thread replied", v.get("status") == "replied" and v.get("review_id") == review_id, v)

finish()
