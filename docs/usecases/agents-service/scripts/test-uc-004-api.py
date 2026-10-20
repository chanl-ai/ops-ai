"""uc-004 complex workflow: fan-out, grade loop, review pause and send, api layer: docs/usecases/agents-service/complex-workflow.md."""

from __future__ import annotations

from usecase_harness import EMAILS, agents, check, data, finish, new_thread, nodes, run, state

with agents() as api:
    tid = new_thread(api, "complex_workflow")
    # The first grade is forced low, so the draft must be redone once before the review.
    code, events = run(api, tid, {"input": {"email": EMAILS[0], "grade_overrides": [0.4]}})
    check("run streamed (200)", code == 200, code)
    ran = nodes(events)
    check("extract fanned out over three attachments", ran.count("extract") == 3, ran)
    check("grade loop redrafted once", ran.count("draft") == 2 and ran.count("grade") == 2, ran)
    check("run paused for review", events[-1]["data"]["status"] == "interrupted", events[-1])
    paused = state(api, tid)
    check(
        "pause is a review interrupt",
        (paused.get("interrupt") or {}).get("payload", {}).get("kind") == "review",
        paused.get("interrupt"),
    )
    check("nothing sent before the decision", not paused["values"].get("sent"), paused["values"].get("sent"))

    # A review is decided in Reviews only; resuming it on the run stream would skip the decision's checks.
    code, _ = run(api, tid, {"resume": {"decision": "approved"}})
    check("resume on the run stream refused (409)", code == 409, code)
    decided = api.post(f"/reviews/{tid}/decision", json={"decision": "approved"})
    check("decided in Reviews (200)", decided.status_code == 200, decided.text[:200])
    # Non-vacuous: the same decision again must not resume again; if it did, the reply would go twice.
    again = api.post(f"/reviews/{tid}/decision", json={"decision": "approved"})
    check("repeated decision accepted without a second resume (200)", again.status_code == 200, again.text[:200])
    sends = sum(r["nodes"].count("send_reply") for r in data(api.get(f"/v1/threads/{tid}/runs")))
    check("send_reply ran exactly once", sends == 1, sends)
    v = state(api, tid)["values"]
    check(
        "thread replied with an outbound id",
        v.get("status") == "replied" and str(v.get("sent", "")).startswith("OUT-"),
        v,
    )

finish()
