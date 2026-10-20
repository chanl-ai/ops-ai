"""uc-254 a builder copies a task type and an API caller opens typed Human Tasks, api layer.

Doc: docs/usecases/agents-service/typed-human-tasks.md. The agents service and a workflow worker on the use case
database; no model is called.
"""

from __future__ import annotations

from typing import Any

from usecase_harness import TEAM, agents, check, data, engine_worker, finish, until

CALLER = {**TEAM, "X-Dev-User": "lee@northfieldbank.com"}
REVIEWER = {**TEAM, "X-Dev-User": "m.okafor@northfieldbank.com"}
FACTS = [{"label": "Vendor", "value": "Acme Supplies"}, {"label": "New account", "value": "****4410"}]

with agents() as api, engine_worker("uc254"):
    # 1. The five general types are seeded and read-only.
    types = data(api.get("/v1/task-types", headers=CALLER))
    seeded = {t["id"] for t in types if t["origin"] == "seed"}
    check(
        "the five general types are seeded",
        {"generic_decision", "document_check", "write_approval", "acknowledgement", "data_entry"} <= seeded,
        sorted(seeded),
    )
    seed = data(api.get("/v1/task-types/write_approval", headers=CALLER))["versions"][0]["record"]
    locked = api.put("/v1/task-types/write_approval/draft", json=seed, headers=CALLER)
    check("a seeded type cannot be edited (409 seed_read_only)", locked.status_code == 409, locked.text[:200])

    # 2. A copy with its own question, published as v1.
    header = {"region": "header", "bind": {"title": "Change the bank account for {vendor} to {account}?"}}
    props = {**seed["params"]["properties"], "vendor": {"type": "string"}, "account": {"type": "string"}}
    mine: dict[str, Any] = {
        "id": "vendor_bank_change",
        "copyOf": {"id": "write_approval"},
        "name": "Vendor bank change",
        # The question reads vendor and account, so those are required in place of the seed's title.
        "params": {**seed["params"], "properties": props, "required": ["vendor", "account", "call"]},
        "regions": [header, *seed["regions"][1:]],
    }
    made = api.post("/v1/task-types", json=mine, headers=CALLER)
    check(
        "a team copies write_approval (201, draft v1)",
        made.status_code == 201 and data(made)["version"] == 1,
        made.text[:200],
    )
    published = api.post("/v1/task-types/vendor_bank_change/publish", json={"version": 1}, headers=CALLER)
    check("its v1 is published", published.status_code == 200, published.text[:200])

    # 3. An API caller opens a task on it with no version: it pins v1.
    params = {"vendor": "Acme Supplies", "account": "****4410", "facts": FACTS}
    posted = api.post("/v1/tasks", json={"type": "vendor_bank_change", "params": params}, headers=CALLER)
    task = data(posted) if posted.status_code == 201 else {}
    check(
        "the task is opened (201) on v1 with a page URL that answers at once",
        (task.get("version"), task.get("url", "")[:9], task.get("status")) == (1, "/reviews/", "waiting"),
        posted.text[:300],
    )
    # The write itself was not passed: a warning, never a refusal.
    check(
        "a missing required value is a warning (call), not a refusal",
        [w["field"] for w in task.get("warnings", [])] == ["call"],
        task.get("warnings"),
    )

    # 4. The type moves on to v2; the open task keeps v1's question.
    v2 = {**data(api.get("/v1/task-types/vendor_bank_change", headers=CALLER))["versions"][0]["record"]}
    v2["regions"] = [{"region": "header", "bind": {"title": "New bank details for {vendor}"}}, *v2["regions"][1:]]
    api.put("/v1/task-types/vendor_bank_change/draft", json=v2, headers=CALLER)
    moved = api.post("/v1/task-types/vendor_bank_change/publish", json={"version": 2}, headers=CALLER)
    check("v2 is published", moved.status_code == 200, moved.text[:200])

    def opened() -> dict[str, Any] | None:
        res = api.get(f"/reviews/{task.get('id')}", headers=REVIEWER)
        return data(res) if res.status_code == 200 and data(res).get("task") else None

    review = until(opened) or {}
    typed = review.get("task") or {}
    regions = {r["region"]: r["data"] for r in typed.get("regions", [])}
    check(
        "the open task still shows v1's question",
        typed.get("type", {}).get("version") == 1
        and regions.get("header") == {"title": "Change the bank account for Acme Supplies to ****4410?"},
        typed.get("type"),
    )
    check(
        "its facts are drawn and the empty write region is left out",
        regions.get("facts") == {"facts": FACTS} and "write_preview" not in regions,
        list(regions),
    )
    check(
        "its actions come in the type's order with their consequence",
        [(a["label"], a["consequence"]) for a in typed.get("actions", [])]
        == [("Make the change", "The change is made now."), ("Decline", "Nothing changes.")],
        typed.get("actions"),
    )

    # 5. A value of the wrong kind is refused naming the field.
    wrong = api.post(
        "/v1/tasks", json={"type": "vendor_bank_change", "params": {**params, "facts": "Acme"}}, headers=CALLER
    )
    check(
        "a wrong-kind value is refused (422 invalid_task_params naming facts)",
        wrong.status_code == 422 and "facts" in wrong.text,
        wrong.text[:200],
    )

    # 6. A person declines it in Human Tasks; the caller reads the decision back.
    decided = api.post(
        f"/reviews/{task.get('id')}/decision",
        json={"decision": "rejected", "reason": "Call the vendor first"},
        headers=REVIEWER,
    )
    check("the reviewer declines it (200)", decided.status_code == 200, decided.text[:200])

    def done() -> dict[str, Any] | None:
        res = api.get(f"/v1/tasks/{task.get('id')}", headers=CALLER)
        return data(res) if res.status_code == 200 and data(res).get("action") else None

    state = until(done) or {}
    check(
        "the caller reads the action, reason and decider",
        (state.get("action"), state.get("reason"), state.get("decidedBy"))
        == ("reject", "Call the vendor first", "m.okafor@northfieldbank.com"),
        state,
    )

finish()
