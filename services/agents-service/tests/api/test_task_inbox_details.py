"""What a decider needs on a Human Task, by failure mode: a chat write names its step by the tool's id and its amount
in an invented USD; a task needing two approvals never says how many or that the reader already approved (a workflow
step's approvals always read empty); the More menu offers Assign, Reassign or Return where the route then refuses it;
a search by the customer or the case's name finds nothing, or finds a task by a name the reader may not read."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from ops_agents.api import engine_reviews, hitl_facade
from ops_agents.api.tool_access import WritePolicy
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import RunStore
from tests.api.test_action_roles import REVIEWER
from tests.api.test_agent_registry import _app  # pyright: ignore[reportPrivateUsage]
from tests.api.test_case_page import _linked_run, data, typed_case  # pyright: ignore[reportPrivateUsage]
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.api.test_write_approval_policy import (
    dev_platform,  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
    drafted,
    person,
)
from tests.engine.test_lifecycle_rights import TENANT, VIEWER

RIGHTS = ("canAssign", "canReassign", "canReturn")


def _policy(approvers: int) -> Any:
    async def fake(_rt: Any, _tool: str) -> WritePolicy:
        return WritePolicy("write", approvers)

    return fake


async def test_a_chat_write_names_its_step_in_words_and_says_two_approve_it(
    dev_platform: AsyncClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hitl_facade, "policy_of", _policy(2))
    james, maya = person("usr_james", ["team_ops"], role="viewer"), person("usr_maya", ["team_ops"])
    thread = (await drafted(dev_platform, james)).split("/")[3]
    review = data(await dev_platform.get(f"/reviews/{thread}", headers=maya))
    assert review["actionLabel"] == "Send a request for proof of address", review.get("actionLabel")
    # The call carries no currency, so none is invented.
    assert review["currency"] is None, review["currency"]
    assert (review["approvalsNeeded"], review["viewerApproved"]) == (2, False), review
    # Return is not a decision a chat write takes, so it is never offered.
    assert review["canReturn"] is False, review
    returned = await dev_platform.post(f"/reviews/{thread}/decision", json={"decision": "returned"}, headers=maya)
    assert returned.status_code == 400, returned.text


async def _held(s: Stack, *, title: str = "Hold the account") -> tuple[str, str]:
    """A workflow run on a case, waiting on one held place_hold for Marcus Bell; its review id and the case id."""
    _, rt = s
    case_id = await typed_case(s)
    run = await _linked_run(s, case_id, "inbox_hold")
    call = {"tool": "place_hold", "input": {"account_id": "CHQ-2219", "amount": 3250, "reason": "NS-1"},
            "step": f"{run}:hold:1:1"}  # fmt: skip
    payload = {"node": "review", "iteration": 1, "title": title, "call": call,
               "draft": {"customer": {"name": "Marcus Bell"}}}  # fmt: skip
    waiting = {"node": "review", "iteration": 1, "interruptId": "i1", "payload": payload}
    with tenant_scope(TENANT):
        await RunStore(EngineTransactions(rt.db)).update(run, status="waiting", waiting=waiting)
    return run, case_id


async def test_a_workflow_steps_approvals_are_read_and_the_reader_is_told_they_approved(
    stack: Stack,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_reviews, "policy_of", _policy(2))
    c, _ = stack
    run, _ = await _held(stack)
    first = await c.post(f"/reviews/{run}/decision", json={"decision": "approved"}, headers=REVIEWER)
    assert first.status_code == 200, first.text
    review = data(await c.get(f"/reviews/{run}", headers=REVIEWER))
    assert review["approvals"] == ["maya@harborpine.example"], review["approvals"]
    assert (review["approvalsNeeded"], review["viewerApproved"]) == (2, True), review
    [row] = [r for r in data(await c.get("/reviews", headers=REVIEWER))["data"] if r["id"] == review["id"]]
    assert (row["approvalsNeeded"], row["viewerApproved"]) == (2, True), row


async def test_assign_reassign_and_return_are_offered_exactly_when_their_routes_accept_them(
    stack: Stack,  # noqa: F811
) -> None:
    c, _ = stack
    run, _ = await _held(stack)
    review = data(await c.get(f"/reviews/{run}", headers=REVIEWER))
    assert {k: review[k] for k in RIGHTS} == {"canAssign": True, "canReassign": False, "canReturn": False}, review
    # A workflow step is approved or rejected; returning it is refused, as its canReturn says.
    returned = await c.post(f"/reviews/{run}/decision", json={"decision": "returned"}, headers=REVIEWER)
    assert returned.status_code == 400, returned.text
    viewer = data(await c.get(f"/reviews/{run}", headers=VIEWER))
    assert {k: viewer[k] for k in RIGHTS} == dict.fromkeys(RIGHTS, False), viewer
    refused = await c.post("/reviews/assign", json={"ids": [review["id"]]}, headers=VIEWER)
    assert refused.status_code == 403, refused.text
    assigned = await c.post("/reviews/assign", json={"ids": [review["id"]]}, headers=REVIEWER)
    assert data(assigned)["updated"] == [review["id"]], assigned.text
    after = data(await c.get(f"/reviews/{run}", headers=REVIEWER))
    assert (after["canAssign"], after["canReassign"]) == (False, True), after
    [row] = [r for r in data(await c.get("/reviews", headers=REVIEWER))["data"] if r["id"] == review["id"]]
    assert {k: row[k] for k in RIGHTS} == {k: after[k] for k in RIGHTS}, row


async def test_a_search_finds_a_task_by_its_customer_and_its_case_for_whoever_reads_them(
    stack: Stack,  # noqa: F811
) -> None:
    c, _ = stack
    run, _ = await _held(stack)

    def found(rows: list[dict[str, Any]]) -> bool:
        return any(str(r["id"]).startswith(run) for r in rows)

    for needle in ("marcus bell", "Charged twice"):
        rows = data(await c.get("/reviews", params={"search": needle}, headers=REVIEWER))["data"]
        assert found(rows), (needle, [r["id"] for r in rows])
    # A viewer reads the task masked, so its customer's name is no key for finding it.
    rows = data(await c.get("/reviews", params={"search": "marcus bell"}, headers=VIEWER))["data"]
    assert not found(rows), [r["id"] for r in rows]


async def test_a_publish_request_is_the_task_a_decider_may_return_and_returning_it_is_accepted(tmp_path: Path) -> None:
    """Return is offered on a publish request alone: the one kind whose decision route takes `returned`."""
    async with _app(
        str(tmp_path / "db.sqlite"), registry_auto_approve=False, dev_policies={"requesterMayDecide": False}
    ) as c:
        lee, kim = {"X-Dev-User": "lee@harborpine.example"}, {"X-Dev-User": "kim@harborpine.example"}
        agent = data(await c.post("/v1/agents", json={"name": "Checker", "role": "Checks"}, headers=lee), 201)
        asked = await c.post(f"/v1/agents/{agent['id']}/publish-requests", json={"version": 1, "note": "go"})
        rid = data(asked, 201)["id"]
        review = data(await c.get(f"/reviews/{rid}", headers=kim))
        assert review["canReturn"] is True, review
        # The requester may not decide their own request, so Return is not theirs to give either.
        assert data(await c.get(f"/reviews/{rid}"))["canReturn"] is False
        body = {"decision": "returned", "reason": "Add the missing eval first"}
        returned = data(await c.post(f"/reviews/{rid}/decision", json=body, headers=kim))
        assert returned["status"] == "returned", returned
