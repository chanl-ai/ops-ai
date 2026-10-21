"""The assembled case and case types (c-291), by failure mode: fields come in no declared order or unformatted; a case
type edit changes a case already open; the case does not say what it waits on, or still says so once it is decided;
another team's case or run shows on the page; the page reads one query per run."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from sqlalchemy import event

from ops_agents.api.auth import step_up_signer
from ops_agents.api.file_names import FilesServiceNames
from ops_agents.api.people_names import PlatformPeopleNames
from ops_agents.store.cases import CaseStore
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import RunStore
from ops_engine.store.tables import engine_runs, engine_steps
from ops_files_client.testing import FakeFilesService
from ops_policy import mint_step_up
from tests.api.test_action_roles import REVIEWER
from tests.api.test_activity import FRAUD_BUILDER
from tests.api.test_case_routes import started_run
from tests.api.test_started_by import Platform
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, TENANT, VIEWER


def data(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


async def typed_case(s: Stack, *, customer: str = "C-1001", team: str = "team_ops") -> str:
    """A complaint case pinned at the seeded `complaint` type, its values set out of the type's order with one the
    type does not declare."""
    c, rt = s
    await c.get("/v1/case-types", headers=BUILDER)  # seeds the tenant's case types
    values = {"amount": "1250", "note": "called twice", "complaint": "Charged twice", "category": "fees"}
    with tenant_scope(TENANT):
        opened = await CaseStore(rt.db).open(
            team_id=team,
            subject="Charged twice",
            priority="high",
            by="james@harborpine.example",
            customer_id=customer,
            customer_name="Marcus Bell",
            assignee="james@harborpine.example",
            fields=values,
            type_id="complaint",
            type_version=1,
        )
    return str(opened.case["id"])


async def test_fields_come_in_the_case_types_order_formatted_then_what_it_does_not_declare(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    page = data(await c.get(f"/v1/cases/{await typed_case(stack)}", headers=BUILDER))
    fields = [(f["key"], f["display"], f["declared"]) for f in page["typedFields"]]
    assert fields == [
        ("complaint", "Charged twice", True),
        ("category", "fees", True),
        ("urgency", "", True),
        ("amount", "1,250.00", True),
        ("note", "called twice", False),
    ], fields
    assert page["caseType"] == {"id": "complaint", "version": 1, "name": "Complaint"}
    assert page["fields"]["amount"] == "1250", "the name-to-value map stays as it was for today's page"
    assert page["owner"]["email"] == "james@harborpine.example" and page["customer"]["href"] == "/cases?customer=C-1001"


async def test_editing_a_case_type_changes_no_case_already_open_and_a_viewer_cannot_make_one(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    case_id = await typed_case(stack)
    assert (await c.post("/v1/case-types", json={"id": "fraud_claim", "name": "x"}, headers=VIEWER)).status_code == 403
    bad = await c.post(
        "/v1/case-types",
        json={"id": "fraud_claim", "name": "Fraud", "fields": [{"key": "a", "label": "A", "type": "colour"}]},
        headers=BUILDER,
    )
    assert bad.status_code == 422, bad.text
    seeded = data(await c.get("/v1/case-types/complaint", headers=BUILDER))
    new = [
        {"key": "amount", "label": "Amount", "type": "money"},
        {"key": "complaint", "label": "What happened", "type": "text"},
    ]
    changed = await c.put("/v1/case-types/complaint/draft", json={"name": "Complaint", "fields": new}, headers=BUILDER)
    assert changed.status_code == 403, "a seeded type is a system record, copied to change it"
    copy = data(
        await c.post(
            "/v1/case-types",
            json={"id": "team_complaint", "copyOf": {"id": "complaint"}, "fields": new},
            headers=BUILDER,
        ),
        201,
    )
    published = data(
        await c.post("/v1/case-types/team_complaint/publish", json={"version": copy["version"]}, headers=BUILDER)
    )
    assert (seeded["origin"], published["publishedVersion"], published["copiedFrom"]) == (
        "seed",
        1,
        {"id": "complaint", "version": 1},
    )
    page = data(await c.get(f"/v1/cases/{case_id}", headers=BUILDER))
    assert page["typedFields"][0]["key"] == "complaint", "the open case keeps the version it was opened with"


async def test_the_case_says_what_it_waits_on_until_the_task_is_decided(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    case_id = await typed_case(stack)
    run = await started_run(c, BUILDER, "case_check")
    assert (
        await c.post(f"/v1/cases/{case_id}/events", json={"kind": "run", "ref": run}, headers=BUILDER)
    ).status_code == 201
    waiting = {
        "node": "review",
        "iteration": 1,
        "interruptId": "i1",
        "payload": {"node": "review", "iteration": 1, "title": "Check the complaint"},
    }
    with tenant_scope(TENANT):
        await RunStore(EngineTransactions(rt.db)).update(run, status="waiting", waiting=waiting)
    page = data(await c.get(f"/v1/cases/{case_id}", headers=BUILDER))
    [task] = page["waiting"]
    # The task's own page (c-291), its id encoded as the console's Open link encodes it, not the list's quick view.
    assert (
        task["href"] == f"/reviews/{quote(task['taskId'], safe='')}" and page["nextAction"]["href"] == task["href"]
    ), page
    assert task["group"] == page["nextAction"]["owner"] == "team_ops", "the deciding team, as the task page names it"
    assert [r["id"] for r in page["links"]["runs"]] == [run] and page["workflow"] is None
    decided = await c.post(f"/reviews/{run}/decision", json={"decision": "approved"}, headers=REVIEWER)
    assert decided.status_code == 200, decided.text
    after = data(await c.get(f"/v1/cases/{case_id}", headers=BUILDER))
    assert (after["waiting"], after["nextAction"]) == ([], None), after["waiting"]
    assert (
        "Added a run" in [a["text"] for a in after["activity"]["recent"]]
        and after["activity"]["allHref"] == f"/activity?case={case_id}"
    )


async def test_another_teams_case_for_the_same_customer_is_not_related_and_its_case_not_found(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    mine = await typed_case(stack)
    sibling = await typed_case(stack)
    theirs = await typed_case(stack, team="team_fraud")
    page = data(await c.get(f"/v1/cases/{mine}", headers=BUILDER))
    assert [(x["id"], x["relation"]) for x in page["links"]["cases"]] == [(sibling, "same_customer")], page["links"][
        "cases"
    ]
    assert (await c.get(f"/v1/cases/{theirs}", headers=BUILDER)).status_code == 404
    assert (await c.get(f"/v1/cases/{mine}", headers=FRAUD_BUILDER)).status_code == 404
    perms = data(await c.get(f"/v1/cases/{mine}", headers=VIEWER))["permissions"]
    assert perms["close"] is False, perms


async def _linked_runs(s: Stack, case_id: str, n: int) -> None:
    _, rt = s
    with tenant_scope(TENANT):
        async with EngineTransactions(rt.db).tenant_tx() as conn:
            for i in range(n):
                await conn.execute(
                    engine_runs.insert().values(
                        id=f"wfrun_{case_id[-6:]}{i:03d}",
                        tenant_id=TENANT,
                        team_id="team_ops",
                        workflow_id="wf",
                        version=1,
                        digest="d",
                        run_key=f"{case_id}:{i}",
                        mode="live",
                        status="succeeded",
                        created_by="b@x",
                        created_at="2026-10-19T00:00:00+00:00",
                        updated_at="2026-10-19T00:00:00+00:00",
                    )
                )
        for i in range(n):
            await CaseStore(rt.db).add_event(case_id, "run", ref=f"wfrun_{case_id[-6:]}{i:03d}", detail={}, by="b@x")


async def test_a_case_with_thirty_runs_reads_in_as_many_queries_as_one_with_one(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    one, many = await typed_case(stack), await typed_case(stack, customer="C-2")
    await _linked_runs(stack, one, 1)
    await _linked_runs(stack, many, 30)
    counts: list[int] = []
    for case_id in (one, many):
        seen = 0

        def count(*_: Any) -> None:
            nonlocal seen
            seen += 1

        event.listen(rt.db.sync_engine, "before_cursor_execute", count)
        page = data(await c.get(f"/v1/cases/{case_id}", headers=BUILDER))
        event.remove(rt.db.sync_engine, "before_cursor_execute", count)
        counts.append(seen)
        assert len(page["links"]["runs"]) == (1 if case_id == one else 30)
    assert counts[0] == counts[1], counts


async def _waiting_on(s: Stack, case_id: str, workflows: int) -> None:
    """Runs of `workflows` different workflows on the case, each waiting on a decision."""
    c, rt = s
    for i in range(workflows):
        run = await started_run(c, BUILDER, f"wf{workflows}_{i}_{case_id[-6:]}")
        assert (
            await c.post(f"/v1/cases/{case_id}/events", json={"kind": "run", "ref": run}, headers=BUILDER)
        ).status_code == 201
        waiting = {
            "node": "review",
            "iteration": 1,
            "interruptId": f"i{i}",
            "payload": {"node": "review", "iteration": 1},
        }
        with tenant_scope(TENANT):
            await RunStore(EngineTransactions(rt.db)).update(run, status="waiting", waiting=waiting)


def _reads(statements: list[str]) -> tuple[int, int]:
    """The SELECTs of workflow definitions and of decisions (engine_work) among the statements sent."""
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    return (
        sum("FROM engine_definitions" in s for s in selects),
        sum("FROM engine_work" in s for s in selects),
    )


async def test_the_case_page_and_reviews_read_workflows_and_decisions_once_however_many_runs(stack: Stack) -> None:  # noqa: F811
    """Each page names its runs' workflows and lists their decisions: one statement each whether the runs belong to
    one workflow or five, so the reviews list, which reads every run of the team, does not grow a query per run."""
    c, rt = stack
    counts: list[tuple[int, int, int, int]] = []
    for workflows in (1, 5):
        case_id = await typed_case(stack, customer=f"C-wf{workflows}")
        await _waiting_on(stack, case_id, workflows)
        seen: list[str] = []

        def record(_conn: Any, _cursor: Any, statement: str, *_: Any, into: list[str] = seen) -> None:
            into.append(statement)

        event.listen(rt.db.sync_engine, "before_cursor_execute", record)
        page = data(await c.get(f"/v1/cases/{case_id}", headers=BUILDER))
        on_page = _reads(seen)
        seen.clear()
        listed = await c.get("/reviews", headers=BUILDER)
        event.remove(rt.db.sync_engine, "before_cursor_execute", record)
        assert listed.status_code == 200 and len(page["waiting"]) == workflows, (listed.text[:200], page["waiting"])
        counts.append((*on_page, *_reads(seen)))
    assert counts[0] == counts[1], counts


async def _linked_run(s: Stack, case_id: str, workflow: str) -> str:
    c, _ = s
    run = await started_run(c, BUILDER, workflow)
    assert (
        await c.post(f"/v1/cases/{case_id}/events", json={"kind": "run", "ref": run}, headers=BUILDER)
    ).status_code == 201
    return run


NAMED, UNNAMED = "fil_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "fil_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


async def test_a_linked_file_is_named_by_files_service_when_its_run_gave_only_the_id(stack: Stack) -> None:  # noqa: F811
    """c-434: the case's Linked records and the run page showed a file as its id when the run's input carried the id
    alone; a file files-service cannot name is sent with no name, so the console shows the id as an id."""
    c, rt = stack
    files = FakeFilesService()
    files.files[NAMED] = {"id": NAMED, "tenant": TENANT, "team": "team_ops", "name": "notice.pdf",
        "mime": "application/pdf", "size": 1, "digest": "d", "purpose": "case_attachment", "uploadedBy": "x",
        "scan": {"status": "clean"}, "referenceCount": 0}  # fmt: skip
    rt.file_names = FilesServiceNames(files.client(service="agents", scopes=["files:view"]))
    case_id = await typed_case(stack)
    run = await _linked_run(stack, case_id, "file_check")
    with tenant_scope(TENANT):
        await RunStore(EngineTransactions(rt.db)).update(run, input={"fileId": NAMED, "other": UNNAMED})
    page = data(await c.get(f"/v1/cases/{case_id}", headers=BUILDER))
    assert [(f["fileId"], f["name"]) for f in page["links"]["files"]] == [
        (NAMED, "notice.pdf"),
        (UNNAMED, None),
    ]
    detail = data(await c.get(f"/v1/runs/{run}", headers=BUILDER))
    assert detail["files"] == [{"id": NAMED, "name": "notice.pdf"}, {"id": UNNAMED, "name": None}], detail


async def test_an_approved_hold_reads_the_amount_the_approver_placed(stack: Stack) -> None:  # noqa: F811
    """c-420: an approver changed the proposed 3,250.00 to 2,140.55 and the bank held 2,140.55, while the case's
    Drafted actions row and the task still said 3,250.00."""
    c, rt = stack
    case_id = await typed_case(stack)
    run = await _linked_run(stack, case_id, "hold_check")
    hold = {
        "name": "hold",
        "label": "Hold",
        "call": {"tool": "place_hold", "input": {"account_id": "CHQ-2219", "amount": 3250, "reason": "NS-1"},
                 "step": f"{run}:hold:1:1"},
        "inputs": [{"name": "amount", "type": "number", "minimum": 0.01}],
    }  # fmt: skip
    waiting = {
        "node": "review",
        "iteration": 1,
        "interruptId": "i1",
        "payload": {"node": "review", "iteration": 1, "title": "Hold or flag", "options": [hold]},
    }
    with tenant_scope(TENANT):
        await RunStore(EngineTransactions(rt.db)).update(run, status="waiting", waiting=waiting)
    # place_hold asks each approver for a step-up.
    token = mint_step_up("maya@harborpine.example", step_up_signer(rt))
    decided = await c.post(
        f"/reviews/{run}/decision",
        json={"decision": "hold", "inputs": {"amount": 2140.55}, "stepUpToken": token},
        headers=REVIEWER,
    )
    assert decided.status_code == 200, decided.text
    review = data(await c.get(f"/reviews/{quote(data(decided)['id'], safe='')}", headers=BUILDER))
    assert review["status"] == "approved" and review["amount"] == 2140.55, review["amount"]
    assert "2,140.55" in review["proposal"], review["proposal"]
    assert any(f["value"].startswith("2,140.55") for f in review["options"][0]["fields"]), review["options"]
    page = data(await c.get(f"/v1/cases/{case_id}", headers=BUILDER))
    [action] = page["actions"]
    assert action["status"] == "approved" and "2,140.55" in action["label"], action


async def test_an_approved_hold_the_bank_refused_reads_refused(stack: Stack) -> None:  # noqa: F811
    """c-402: the bank answered 422 to an approved hold and the run went back to its review, while the case's Drafted
    actions still said Approved, so two refused holds read as two placed holds."""
    c, rt = stack
    case_id = await typed_case(stack)
    run = await _linked_run(stack, case_id, "refused_hold")
    step = f"{run}:hold:1:1"
    hold = {"name": "hold", "label": "Hold",
            "call": {"tool": "place_hold", "input": {"account_id": "CHQ-2219", "amount": 3250, "reason": "NS-1"},
                     "step": step}}  # fmt: skip
    waiting = {
        "node": "review",
        "iteration": 1,
        "interruptId": "i1",
        "payload": {"node": "review", "iteration": 1, "title": "Hold or flag", "options": [hold]},
    }
    with tenant_scope(TENANT):
        await RunStore(EngineTransactions(rt.db)).update(run, status="waiting", waiting=waiting)
    token = mint_step_up("maya@harborpine.example", step_up_signer(rt))
    decision = {"decision": "hold", "stepUpToken": token}
    decided = await c.post(f"/reviews/{run}/decision", json=decision, headers=REVIEWER)
    assert decided.status_code == 200, decided.text
    [placed] = data(await c.get(f"/v1/cases/{case_id}", headers=BUILDER))["actions"]
    assert placed["status"] == "approved", placed
    with tenant_scope(TENANT):
        async with EngineTransactions(rt.db).tenant_tx() as conn:
            await conn.execute(
                engine_steps.insert().values(
                    run_id=run,
                    node_id="hold",
                    iteration=1,
                    attempt=1,
                    tenant_id=TENANT,
                    status="error",
                    effects="write",
                    key=step,
                    port="error",
                    started_at="2026-10-20T16:40:59Z",
                    output={"error": {"error": {"code": "INVALID_ARGUMENTS", "status": 422}}},
                )
            )
    [refused] = data(await c.get(f"/v1/cases/{case_id}", headers=BUILDER))["actions"]
    assert refused["status"] == "refused", refused


async def test_the_cases_list_names_each_owner_as_the_case_page_does(stack: Stack) -> None:  # noqa: F811
    """c-403: the Cases list showed riley.chen@harborpine.example where the case page said Riley Chen; the console may
    not look the name up itself, so the list row carries it."""
    c, rt = stack
    rt.people_names = PlatformPeopleNames(Platform())  # pyright: ignore[reportArgumentType]
    case_id = await typed_case(stack)
    listed = data(await c.get("/v1/cases", params={"pageSize": 100}, headers=BUILDER))["data"]
    row = next(r for r in listed if r["id"] == case_id)
    assert row["owner"] == {"email": "james@harborpine.example", "name": "James Richardson"}, row
    assert row["owner"] == data(await c.get(f"/v1/cases/{case_id}", headers=BUILDER))["owner"]
