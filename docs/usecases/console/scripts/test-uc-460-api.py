"""uc-460 a reviewer works Human Tasks, api layer: docs/usecases/console/human-tasks-queue.md. platform-service signs
the seeded people in and agents-service verifies their tokens, as the console runs them; a workflow worker runs the
task. James (builder) opens a write approval through the tasks API; Maya (approver) and Rohan (viewer) read it as the
inbox does. No model is called."""

from __future__ import annotations

from typing import Any

from usecase_harness import as_role, check, data, engine_worker, finish, people_stack, until

CALL = {"tool": "place_hold", "input": {"account_id": "CHQ-2219", "amount": 3250, "currency": "EUR", "reason": "NS-1"}}
RIGHTS = ("canDecide", "canAssign", "canReassign", "canReturn")

with people_stack() as (api, agents), engine_worker("uc460"):
    james, maya, rohan = as_role(api, "builder"), as_role(api, "approver"), as_role(api, "viewer")
    params = {"title": "Hold CHQ-2219 for the levy notice", "call": CALL}
    opened = agents.post("/v1/tasks", json={"type": "write_approval", "params": params}, headers=james)
    check("James opens a write approval through the tasks API (201)", opened.status_code == 201, opened.text[:300])
    task_id = str(data(opened).get("id") if opened.status_code == 201 else "")

    def read(who: dict[str, str]) -> dict[str, Any] | None:
        res = agents.get(f"/reviews/{task_id}", headers=who)
        return data(res) if res.status_code == 200 and data(res).get("status") == "pending" else None

    review = until(lambda: read(maya)) or {}
    review_id = str(review.get("id") or task_id)

    # 1. The step in words, the approvals it needs, and what Maya may do, each as its route allows.
    check(
        "14 the task names the step in words, never the tool id",
        bool(review.get("actionLabel")) and review.get("actionLabel") != "place_hold",
        review.get("actionLabel"),
    )
    check(
        "14b it says how many approve it and that Maya has not",
        review.get("approvalsNeeded", 0) >= 1 and review.get("viewerApproved") is False,
        {k: review.get(k) for k in ("approvalsNeeded", "viewerApproved", "approvals")},
    )
    check(
        "14c Maya may decide and assign it; reassign waits for an assignee and a workflow step is never returned",
        {k: review.get(k) for k in RIGHTS}
        == {"canDecide": True, "canAssign": True, "canReassign": False, "canReturn": False},
        {k: review.get(k) for k in RIGHTS},
    )

    # 2. Rohan reads it as a viewer: no action, and the assign route refuses him as the flags say.
    seen = read(rohan) or {}
    check("15 Rohan may do nothing with it", all(seen.get(k) is False for k in RIGHTS), {k: seen.get(k) for k in RIGHTS})
    refused = agents.post("/reviews/assign", json={"ids": [review_id]}, headers=rohan)
    check("15b his assign is refused (403), as his flags said", refused.status_code == 403, refused.text[:200])

    # 3. Maya assigns it to herself: Assign gives way to Reassign, on the list row as on the task.
    assigned = agents.post("/reviews/assign", json={"ids": [review_id]}, headers=maya)
    check("16 Maya assigns it to herself", assigned.status_code == 200 and data(assigned)["updated"] == [review_id])
    rows = data(agents.get("/reviews", params={"view": "open", "pageSize": 200}, headers=maya))["data"]
    row = next((r for r in rows if r["id"] == review_id), {})
    check(
        "16b the list row now offers Reassign, not Assign",
        (row.get("canAssign"), row.get("canReassign")) == (False, True),
        {k: row.get(k) for k in RIGHTS},
    )

    # 4. Search runs on the server; the customer and case name are matched there too (pytest: test_task_inbox_details).
    found = data(agents.get("/reviews", params={"view": "open", "search": "levy notice"}, headers=maya))["data"]
    check("17 a search finds the task on the server", any(r["id"] == review_id for r in found))
    none = data(agents.get("/reviews", params={"view": "open", "search": "no such customer"}, headers=maya))["data"]
    check("17b a search that matches nothing lists nothing of it", all(r["id"] != review_id for r in none))

finish()
