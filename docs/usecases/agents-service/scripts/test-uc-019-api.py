"""uc-019 create a workflow from draft JSON, validate, test, publish and start it, api layer.

Doc: docs/usecases/agents-service/workflow-draft-publish-start.md.
"""

from __future__ import annotations

import os

# Publishing goes through a second person here, as outside dev: dev's auto-approve is off for this use case.
os.environ["OPS_REGISTRY_AUTO_APPROVE"] = "false"

from usecase_harness import TEAM, agents, check, data, finish, new_thread, nodes, run, state

EMAIL = {
    "sender": "ana@example.com",
    "subject": "Payee",
    "body": "Is the new payee on CHQ-2219 fine?",
    "attachments": [],
}


def node(nid: str, kind: str, **extra: object) -> dict[str, object]:
    return {"id": nid, "type": kind, "position": {"x": 0, "y": 0}, "data": {"label": nid, "description": "", **extra}}


with agents() as api:
    res = api.post(
        "/v1/workflows", json={"name": "Payee check", "trigger": "Payee added", "template": "blank"}, headers=TEAM
    )
    wf = data(res)
    check("workflow created as a draft (201)", res.status_code == 201 and wf["status"] == "draft", res.text[:200])
    wid = wf["id"]

    graph = {
        "nodes": [
            node("t", "trigger"),
            node("assess", "step", agentSlug="wire-fraud-sentinel"),
            node("review", "review"),
            node("held", "end"),
            node("released", "end"),
        ],
        "edges": [
            {"id": "1", "source": "t", "target": "assess"},
            {"id": "2", "source": "assess", "target": "review"},
            {"id": "3", "source": "review", "target": "held", "sourceHandle": "approved"},
            {"id": "4", "source": "review", "target": "released", "sourceHandle": "rejected"},
        ],
    }
    saved = api.put(f"/v1/workflows/{wid}/draft", json={"graph": graph}, headers=TEAM)
    check("draft saved (200)", saved.status_code == 200, saved.text[:200])

    # Non-vacuous pair: the same graph with an unknown agent fails validation and publish; the real one passes both.
    bad = {
        **graph,
        "nodes": [*graph["nodes"][:1], node("assess", "step", agentSlug="no-such-agent"), *graph["nodes"][2:]],
    }
    run_bad = data(api.post(f"/v1/workflows/{wid}/validate", json={"graph": bad}, headers=TEAM))
    refused = api.post(f"/v1/workflows/{wid}/publish-requests", json={"graph": bad, "note": "bad"}, headers=TEAM)
    check(
        "an unknown agent fails validation and publish (422)",
        run_bad["summary"]["checksFailing"] == 1 and refused.status_code == 422,
        [run_bad["summary"], refused.status_code],
    )
    run_ok = data(api.post(f"/v1/workflows/{wid}/validate", json={"graph": graph}, headers=TEAM))
    check("the real graph validates with no failing check", run_ok["summary"]["checksFailing"] == 0, run_ok["summary"])

    test = data(api.post(f"/v1/workflows/{wid}/test", json={"email": EMAIL}, headers=TEAM))
    check(
        "test run reaches held with its review approved",
        test["status"] == "completed" and test["visited"][-1] == "held" and test["pausesApproved"] == 1,
        test,
    )

    lee = {**TEAM, "X-Dev-User": "lee@harborpine.example"}

    def request_publish(note: str) -> dict[str, object]:
        res = api.post(f"/v1/workflows/{wid}/publish-requests", json={"graph": graph, "note": note}, headers=TEAM)
        return data(res)

    def decide(rid: object, body: dict[str, str], headers: dict[str, str]) -> object:
        return api.post(f"/v1/publish-requests/{rid}/decision", json=body, headers=headers)

    first = request_publish("first")
    check("publish request opens pending", first["status"] == "pending", first)
    own = decide(first["id"], {"decision": "approved"}, TEAM)
    check("the requester cannot approve it (403)", own.status_code == 403, own.status_code)
    rejected = data(decide(first["id"], {"decision": "rejected", "reason": "Add the fraud check"}, lee))
    blocked = api.post("/v1/threads", json={"graph": wid}, headers=TEAM)
    check(
        "rejected by a second person: nothing published, threads refused (400)",
        rejected["status"] == "rejected" and blocked.status_code == 400,
        [rejected["status"], blocked.status_code],
    )
    second = request_publish("second")
    res = decide(second["id"], {"decision": "approved"}, lee)
    review = data(res)
    check(
        "a second request approved by a second person publishes v1 with a digest",
        res.status_code == 200 and review["status"] == "approved" and len(review["publish"]["digest"]) == 64,
        res.text[:200],
    )
    check("listed in GET /v1/graphs", wid in {g["name"] for g in data(api.get("/v1/graphs", headers=TEAM))})

    tid = new_thread(api, wid)
    code, events = run(api, tid, {"input": {"email": EMAIL}})
    check("started: runs to the review and waits", code == 200 and nodes(events)[-1] == "review", nodes(events))
    check("the thread is pinned to v1", state(api, tid)["version"] == 1)
    runs = data(api.get(f"/v1/workflows/{wid}/runs", headers=TEAM))
    check("its run is listed as waiting for review", runs["data"][0]["status"] == "waiting_review", runs["data"][:1])

    # A router: subject "urgent" goes to the review, anything else to the end. The failing twin compares a field
    # the state does not have; it must fail at validation, not when a thread reaches the router.
    def routed(field: str) -> dict[str, object]:
        router = node("route", "router", routes={"urgent": {"field": field, "op": "eq", "value": "urgent"}})
        router["data"]["defaultRoute"] = "other"  # type: ignore[index]
        return {
            "nodes": [node("t", "trigger"), router, node("review", "review"), node("held", "end"), node("done", "end")],
            "edges": [
                {"id": "1", "source": "t", "target": "route"},
                {"id": "2", "source": "route", "target": "review", "sourceHandle": "urgent"},
                {"id": "3", "source": "route", "target": "done", "sourceHandle": "other"},
                {"id": "4", "source": "review", "target": "held", "sourceHandle": "approved"},
                {"id": "5", "source": "review", "target": "done", "sourceHandle": "rejected"},
            ],
        }

    good = data(api.post(f"/v1/workflows/{wid}/validate", json={"graph": routed("email.subject")}, headers=TEAM))
    bad = data(api.post(f"/v1/workflows/{wid}/validate", json={"graph": routed("amount")}, headers=TEAM))
    failures = [r["draft"].get("failure", "") for r in bad["results"] if not r["draft"]["passed"]]
    check("a two-route router validates", good["summary"]["checksFailing"] == 0, good["summary"])
    check("a router on an unknown field fails validation", any("unknown field amount" in f for f in failures), failures)
    urgent = data(
        api.post(
            f"/v1/workflows/{wid}/test",
            json={"graph": routed("email.subject"), "email": {**EMAIL, "subject": "urgent"}},
            headers=TEAM,
        )
    )
    plain = data(
        api.post(f"/v1/workflows/{wid}/test", json={"graph": routed("email.subject"), "email": EMAIL}, headers=TEAM)
    )
    check(
        "urgent goes to the review, anything else to the default",
        "review" in urgent["visited"] and plain["visited"] == ["t", "route", "done"],
        [urgent["visited"], plain["visited"]],
    )

    api.delete(f"/v1/workflows/{wid}", headers=TEAM)
    after = api.post("/v1/threads", json={"graph": wid}, headers=TEAM)
    check("deleted: new threads refused (404)", after.status_code == 404, after.status_code)

finish()
