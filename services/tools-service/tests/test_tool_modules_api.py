"""/v1/tool-modules through the real routes, one test per way the registry could break the console's rules. Every
JSON response is also validated against openapi.json by the fixture's contract checker."""

from __future__ import annotations

from typing import Any

import pytest

from .conftest import Api

OTHER = "Priya Shah"


async def _ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


async def test_list_serves_the_console_contract(api: Api, seed: dict[str, Any]) -> None:
    data = await _ok(await api.call("GET", "", params={"page": 1, "pageSize": 50}))
    # The mock's blank draft, and the module holding the agents catalogue's demo tools.
    assert data["pagination"]["total"] == len(seed["modules"]) + 2
    assert data["viewCounts"]["all"] == data["stats"]["modules"]
    assert set(data["facets"]) == {"type", "access", "approvalState"}
    expired = await _ok(await api.call("GET", "", params={"view": "expired"}))
    assert [m["id"] for m in expired["data"]] == ["mod_sharepoint"], "the one module whose only approval lapsed"
    writes = await _ok(await api.call("GET", "", params={"access": "write", "pageSize": 50}))
    assert writes["data"] and all("write" in m["accessClasses"] for m in writes["data"])
    retired = await api.call("GET", "", params={"access": "money_movement"})
    assert retired.status_code == 200 and retired.json()["data"]["data"] == [], "no module has the retired class"


async def test_a_team_sees_only_its_modules_and_is_told_who_owns_the_rest(api: Api) -> None:
    lending = await _ok(await api.call("GET", "", team="team_lending", params={"pageSize": 50}))
    owners = {m["ownerTeam"] for m in lending["data"]}
    assert "Core Banking Platform" in owners, "seen through the Lending Ops workflow approved for it"
    assert "Payments Operations" not in owners
    r = await api.call("GET", "/mod_payments_hub", team="team_lending")
    assert r.status_code == 404, "another team's module answers 404, naming no owner (c-423)"


async def test_a_literal_credential_in_a_header_is_refused(api: Api) -> None:
    op = {
        "name": "get_statement",
        "description": "Monthly statement",
        "access": "read",
        "method": "GET",
        "url": "https://statements.example.com/v1/accounts/{accountId}/statement",
        "headers": [{"key": "Authorization", "value": "Bearer sk_live_abc123"}],
    }
    r = await api.call("POST", "/mod_document_service/operations", json=op)
    assert r.status_code == 400 and "literal value" in r.json()["error"]["message"]
    op["headers"] = [{"key": "Authorization", "value": "{{STATEMENTS_TOKEN}}"}]
    await api.client.post("/v1/egress/hosts", json={"value": "statements.example.com"})
    detail = await _ok(await api.call("POST", "/mod_document_service/operations", json=op))
    added = next(o for o in detail["operations"] if o["name"] == "get_statement")
    assert [f["name"] for f in added["input"]] == ["accountId"]
    assert detail["egressHosts"] == ["statements.example.com"]


async def test_an_expired_approval_lets_no_call_through(api: Api) -> None:
    body = {"operation": "search_sites", "contextId": "wf_advisor", "target": "stub", "input": {"query": "x"}}
    result = await _ok(await api.call("POST", "/mod_sharepoint/test", json=body))
    assert (result["decision"], result["denyReason"]) == ("deny", "approval_expired")


async def test_a_major_change_opens_a_security_review_and_a_minor_one_does_not(api: Api) -> None:
    detail = await _ok(await api.call("GET", "/mod_core_banking"))
    write = next(o for o in detail["operations"] if o["access"] == "write" and o["requiresApproval"])
    read = next(o for o in detail["operations"] if o["access"] == "read")

    await _ok(await api.call("PATCH", f"/mod_core_banking/operations/{read['id']}", json={"rateLimitPerMin": 30}))
    minor = await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Slower reads"}))
    a, b, _ = detail["version"].split(".")
    assert minor["version"] == f"{a}.{int(b) + 1}.0"
    assert minor["versions"][0]["status"] == "published"

    patch = {"requiresApproval": False}
    staged = await _ok(await api.call("PATCH", f"/mod_core_banking/operations/{write['id']}", json=patch))
    assert staged["pendingChanges"][0]["major"] is True, "dropping a person's approval widens what a write can do"
    major = await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Writes run unattended"}))
    assert major["version"] == f"{int(a) + 1}.0.0"
    assert major["versions"][0]["status"] == "in_review"
    assert major["versions"][0]["reviewId"] and major["pendingReview"]["id"] == major["versions"][0]["reviewId"]
    assert major["approvalState"] == "needs_approval"


async def test_an_operation_two_people_approve_cannot_drop_its_approval(api: Api) -> None:
    detail = await _ok(await api.call("GET", "/mod_payments_hub"))
    two = next(o for o in detail["operations"] if o["approvers"] == 2)
    r = await api.call("PATCH", f"/mod_payments_hub/operations/{two['id']}", json={"requiresApproval": False})
    assert r.status_code == 422


async def test_an_amount_limit_is_refused_on_an_operation_with_no_amount_input(api: Api) -> None:
    """The gateway reads the limit from the `amount` input (c-028); a limit on an operation without one would be
    shown and never hold."""
    hub = await _ok(await api.call("GET", "/mod_payments_hub"))
    wire = next(o for o in hub["operations"] if o["name"] == "place_wire_hold")
    r = await api.call("PATCH", f"/mod_payments_hub/operations/{wire['id']}", json={"amountMax": 1000})
    assert r.status_code == 422 and "no amount input" in r.json()["error"]["message"], r.text
    bank = await _ok(await api.call("GET", "/mod_core_banking"))
    transfer = next(o for o in bank["operations"] if o["name"] == "transfer_funds")
    assert (
        await api.call("PATCH", f"/mod_core_banking/operations/{transfer['id']}", json={"amountMax": 1000})
    ).status_code == 200


async def test_a_body_naming_an_unknown_field_is_refused(api: Api) -> None:
    body = {"displayName": "Payroll", "name": "payroll", "type": "http", "tenantId": "someone-else"}
    r = await api.call("POST", "/blank", json=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_failed"


@pytest.mark.parametrize("dev", [False], ids=["production"])
async def test_outside_dev_a_header_cannot_name_who_decides(api: Api) -> None:
    """Outside dev the caller comes from a platform token or key only: X-Dev-User names nobody, and with no
    credentials the request is refused rather than run as a default person."""
    r = await api.call("POST", "/mod_core_banking/approvals/apr_x/decide", user=OTHER, json={"decision": "approved"})
    assert r.status_code == 401, r.text
    assert (await api.call("GET", "")).status_code == 401


async def test_a_first_review_approved_in_reviews_publishes_the_module(api: Api) -> None:
    """Who may approve is Reviews' rule (c-163); here the approval it sends publishes the version."""
    await api.client.post("/v1/egress/hosts", json={"value": "statements.example.com"})
    op = {
        "name": "get_statement",
        "description": "Monthly statement",
        "access": "read",
        "method": "GET",
        "url": "https://statements.example.com/v1/accounts/{accountId}/statement",
    }
    await _ok(await api.call("POST", "/mod_document_service/operations", json=op))
    reviewed = await _ok(await api.call("POST", "/mod_document_service/reviews", json={"note": "First version"}))
    assert reviewed["status"] == "in_review" and reviewed["pendingReview"]["id"] == reviewed["versions"][0]["reviewId"]
    done = await _ok(await api.decide("mod_document_service"))
    assert (done["status"], done["versions"][0]["status"]) == ("published", "published")
