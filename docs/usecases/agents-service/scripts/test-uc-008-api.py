"""uc-008 a paused workflow is decided from the console, api layer:
docs/usecases/agents-service/decide-paused-workflow.md."""

from __future__ import annotations

from usecase_harness import EMAILS, TEAM, agents, check, data, finish, new_thread, run

with agents() as api:
    tid = new_thread(api, "complex_workflow")
    code, events = run(api, tid, {"input": {"email": EMAILS[0]}})
    check("dispute run paused for review", code == 200 and events[-1]["data"]["status"] == "interrupted", events[-1])

    rows = data(api.get("/runs", params={"view": "needs_person", "page": 1, "pageSize": 25}))
    row = next((r for r in rows["data"] if r["id"] == tid), None)
    check("the run is a Cases row waiting on a person", row is not None and row["state"] == "waiting", row)
    sheet = data(api.get(f"/runs/{tid}"))
    waiting = [s["nodeId"] for s in sheet["steps"] if s["status"] == "waiting"]
    check(
        "run sheet lists the node steps, paused at the review",
        sheet["steps"][1:4] and waiting == ["human"],
        sheet["steps"],
    )

    review = data(api.get(f"/reviews/{tid}"))
    check(
        "the review is pending and does not move money",
        review["status"] == "pending" and not review["stepUp"],
        review,
    )
    decided = api.post(f"/reviews/{tid}/decision", json={"decision": "approved"}, headers=TEAM)
    check("approved without a step-up (write, not money) (200)", decided.status_code == 200, decided.text)
    # Non-vacuous: a repeated decision must not resume again; a facade that resumed twice would send twice.
    again = api.post(f"/reviews/{tid}/decision", json={"decision": "approved"}, headers=TEAM)
    check("repeated decision accepted without a second resume (200)", again.status_code == 200, again.text)
    journal = data(api.get(f"/v1/threads/{tid}/runs"))
    check("send_reply ran exactly once", sum(r["nodes"].count("send_reply") for r in journal) == 1, journal)
    done = data(api.get(f"/runs/{tid}"))
    check("the row finished", done["state"] == "done" and done["status"] == "completed", done)
    open_rows = data(api.get("/runs", params={"view": "needs_person", "page": 1, "pageSize": 25}))["data"]
    check("it left Needs a person", all(r["id"] != tid for r in open_rows), open_rows)

finish()
