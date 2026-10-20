"""The write approval policy per operation (c-048 T005), by failure mode: a policy no reviewer could satisfy saved, a
money operation left with one approver, an approving team that does not exist, and a loosened policy taking effect
before Security reviews it. OPA's side, a token with too few approvers, is in test_calls.py."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.modules.seed import load
from ops_tools.registry import approval_policy
from ops_tools.store.modules import ModuleStore

from .conftest import Api, service_headers


async def _ok(r: httpx.Response) -> Any:
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _op(api: Api, module: str, name: str) -> dict[str, Any]:
    detail = await _ok(await api.call("GET", f"/{module}"))
    return next(o for o in detail["operations"] if o["name"] == name)


async def _policy(api: Api, name: str) -> dict[str, Any]:
    r = await api.client.get(f"/v1/tools/{name}", headers=service_headers(api.tenant))
    return dict((await _ok(r))["approval"])


async def test_an_operation_shows_its_policy_with_the_owning_team_by_default(api: Api) -> None:
    op = await _op(api, "mod_core_banking", "update_address")
    detail = await _ok(await api.call("GET", "/mod_core_banking"))
    assert op["approvers"] == 1 and "selfApproval" not in op, (
        "the requester rule is the tenant policy, not the operation"
    )
    assert str(op["approverTeam"]).startswith("team_"), detail["ownerTeam"]
    assert await _policy(api, "update_address") == {
        "approvers": 1,
        "approverTeam": op["approverTeam"],
        "stepUp": False,
    }


async def test_a_step_up_can_be_asked_of_one_approver_and_is_implied_by_two(api: Api) -> None:
    """c-057: a hold on a customer's funds is approved by one person, who still re-authenticates. The setting is
    part of the approval policy, so Security reviews it like the rest; until then calls keep the published one."""
    op = await _op(api, "mod_core_banking", "update_address")
    path = f"/mod_core_banking/operations/{op['id']}"
    staged = await _ok(await api.call("PATCH", path, json={"stepUp": True}))
    assert next(c for c in staged["pendingChanges"] if "step-up" in c["detail"])["major"] is True
    assert (await _policy(api, "update_address"))["stepUp"] is False, "a staged edit waits for publish"
    await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "step-up on"}))
    await _ok(await api.decide("mod_core_banking"))
    assert (await _op(api, "mod_core_banking", "update_address"))["stepUp"] is True
    assert (await _policy(api, "update_address"))["stepUp"] is True
    offered = await api.client.get("/v1/grantable-operations", headers=service_headers(api.tenant))
    assert next(o for o in offered.json()["data"] if o["name"] == "update_address")["stepUp"] is True
    two = await _op(api, "mod_core_banking", "transfer_funds")
    assert two["approvers"] == 2 and two["stepUp"] is True, "two approvers always step up"


async def test_a_policy_nobody_could_satisfy_is_refused(api: Api) -> None:
    op = await _op(api, "mod_core_banking", "update_address")
    path = f"/mod_core_banking/operations/{op['id']}"
    assert (await api.call("PATCH", path, json={"approvers": 3})).status_code == 400
    assert (await api.call("PATCH", path, json={"approverTeam": "team_nobody"})).status_code == 422
    retired = {
        "name": "move_it",
        "description": "",
        "access": "money_movement",
        "method": "GET",
        "url": "https://x.test/a",
    }
    r = await api.call("POST", "/mod_core_banking/operations", json=retired)
    assert r.status_code == 400 and "access" in r.json()["error"]["message"], r.text


async def test_tightening_applies_once_published(api: Api) -> None:
    op = await _op(api, "mod_core_banking", "update_address")
    staged = await _ok(
        await api.call(
            "PATCH", f"/mod_core_banking/operations/{op['id']}", json={"approvers": 2, "approverTeam": "team_ops"}
        )
    )
    assert any(c["major"] for c in staged["pendingChanges"]), "another approving team is reviewed by Security"
    assert (await _policy(api, "update_address"))["approvers"] == 1, "a staged edit waits for publish"


async def test_a_loosened_policy_waits_for_security(api: Api) -> None:
    op = await _op(api, "mod_core_banking", "update_address")
    staged = await _ok(
        await api.call("PATCH", f"/mod_core_banking/operations/{op['id']}", json={"approverTeam": "team_retail"})
    )
    assert staged["pendingChanges"][0]["major"] is True
    assert (await _policy(api, "update_address"))["approverTeam"] != "team_retail", "staged, not applied"
    review = await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Askers approve"}))
    assert review["versions"][0]["status"] == "in_review"
    assert (await _policy(api, "update_address"))["approverTeam"] != "team_retail", (
        "the published policy holds during review"
    )
    await _ok(await api.decide("mod_core_banking"))
    assert (await _policy(api, "update_address"))["approverTeam"] == "team_retail", "applied once Security approved"


async def test_nothing_is_edited_or_published_while_a_version_waits_for_security(api: Api) -> None:
    """An edit or a version on top of one in review would leave Security approving something that is no longer what
    calls switch to, so the reviewed policy could never apply as reviewed."""
    op = await _op(api, "mod_core_banking", "update_address")
    path = f"/mod_core_banking/operations/{op['id']}"
    await _ok(await api.call("PATCH", path, json={"approverTeam": "team_retail"}))
    await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Askers approve"}))
    edit = await api.call("PATCH", path, json={"description": "Change a customer's mailing address"})
    assert edit.status_code == 409, edit.text
    minor = await api.call("POST", "/mod_core_banking/versions", json={"note": "Wording"})
    assert minor.status_code in (400, 409), minor.text
    assert (await _policy(api, "update_address"))["approverTeam"] != "team_retail"
    await _ok(await api.decide("mod_core_banking"))
    assert (await _policy(api, "update_address"))["approverTeam"] == "team_retail", "Security's approval takes effect"
    assert (
        await api.call("PATCH", path, json={"description": "Change a customer's mailing address"})
    ).status_code == 200


async def _loosen_and_request(api: Api) -> tuple[str, dict[str, Any]]:
    op = await _op(api, "mod_core_banking", "update_address")
    path = f"/mod_core_banking/operations/{op['id']}"
    await _ok(await api.call("PATCH", path, json={"approverTeam": "team_retail"}))
    return path, await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Askers approve"}))


async def test_no_operation_is_added_or_discarded_while_a_version_waits_for_security(api: Api) -> None:
    _, major = await _loosen_and_request(api)
    endpoint = major["endpoint"].rstrip("/")
    new = {"name": "close_account_t017", "description": "", "access": "write", "method": "POST", "url": f"{endpoint}/x"}
    assert (await api.call("POST", "/mod_core_banking/operations", json=new)).status_code == 409
    assert (await api.call("DELETE", "/mod_core_banking/pending-changes")).status_code == 409
    await _ok(await api.decide("mod_core_banking"))
    assert (await _policy(api, "update_address"))["approverTeam"] == "team_retail", "the approved version applies"


async def test_changes_requested_ends_the_review_and_unlocks_edits(api: Api) -> None:
    path, _ = await _loosen_and_request(api)
    decided = await _ok(await api.decide("mod_core_banking", "returned", "Askers must not approve their own writes"))
    assert not any(v["status"] == "in_review" for v in decided["versions"])
    assert (await _policy(api, "update_address"))["approverTeam"] != "team_retail", "the declined policy never applies"
    assert (await api.call("PATCH", path, json={"description": "Change a mailing address"})).status_code == 200


async def test_a_declined_change_never_goes_live_by_a_later_minor_edit(api: Api) -> None:
    path, _ = await _loosen_and_request(api)
    await _ok(await api.decide("mod_core_banking", "returned", "Askers must not approve their own writes"))
    await _ok(await api.call("PATCH", path, json={"description": "Change a customer's mailing address"}))
    again = await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Wording"}))
    assert again["versions"][0]["status"] == "in_review", "the declined policy still differs, so this is major"
    assert (await _policy(api, "update_address"))["approverTeam"] != "team_retail"


async def test_a_staged_limit_raise_or_binding_removal_is_not_served_until_reviewed(
    api: Api, engine: AsyncEngine
) -> None:
    op = await _op(api, "mod_core_banking", "transfer_funds")
    assert op.get("binding") and op.get("amountMax"), op
    path = f"/mod_core_banking/operations/{op['id']}"
    await _ok(await api.call("PATCH", path, json={"amountMax": 9_999_999, "binding": None}))
    found = await ModuleStore(engine).operation_named(api.tenant, "transfer_funds")
    assert found is not None
    served = found[1]
    assert float(served["amount_max"]) == float(op["amountMax"]) and served["binding"], "staged, so not served"
    await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Bigger transfers"}))
    await _ok(await api.decide("mod_core_banking", "returned", "Keep the limit and the binding"))
    await _ok(await api.call("PATCH", path, json={"description": "Move money between a customer's accounts"}))
    again = await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Wording"}))
    assert again["versions"][0]["status"] == "in_review", "the declined limit and binding still differ, so major"


async def test_a_staged_new_operation_is_not_served_or_grantable_until_approved(api: Api, engine: AsyncEngine) -> None:
    detail = await _ok(await api.call("GET", "/mod_core_banking"))
    endpoint = detail["endpoint"].rstrip("/")
    new = {"name": "close_account_zz", "description": "", "access": "write", "method": "POST", "url": f"{endpoint}/z"}
    await _ok(await api.call("POST", "/mod_core_banking/operations", json=new))

    async def served() -> bool:
        tool = await api.client.get("/v1/tools/close_account_zz", headers=service_headers(api.tenant))
        listed = await api.client.get("/v1/grantable-operations", headers=service_headers(api.tenant))
        names = {o["name"] for o in listed.json()["data"]}
        resolved = await ModuleStore(engine).operation_named(api.tenant, "close_account_zz")
        assert (tool.status_code == 200) == ("close_account_zz" in names) == (resolved is not None)
        return resolved is not None

    assert not await served(), "staged: not served, listed or grantable"
    await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Close accounts"}))
    assert not await served(), "in review: still not served"
    await _ok(await api.decide("mod_core_banking"))
    assert await served(), "served once Security approved"


async def test_a_module_created_in_a_team_files_that_team_as_its_approver(api: Api) -> None:
    """G33: James works in team_ops, an all-scope team; his new module fell back to the first all-scope team
    (team_platform), which platform-service does not know, so the operation sheet named an id instead of a team."""
    body = {"displayName": "Levy desk", "name": "levy-desk", "type": "http"}
    created = await api.call("POST", "/blank", json=body, team="team_ops")
    assert created.status_code == 201, created.text
    module = created.json()["data"]["id"]
    write = {
        "name": "flag_levy",
        "description": "",
        "access": "write",
        "method": "POST",
        "url": "https://statements.example.com/a",
    }
    await api.client.post("/v1/egress/hosts", json={"value": "statements.example.com"})
    added = await api.call("POST", f"/{module}/operations", json=write, team="team_ops")
    assert added.status_code in (200, 201), added.text
    op = await _op(api, module, "flag_levy")
    assert op["approverTeam"] == "team_ops"


async def test_the_seeded_wire_hold_is_approved_by_two_people_of_fraud_operations(
    engine: AsyncEngine, catalog_tools: list[dict[str, Any]]
) -> None:
    """The seed the stack starts from (seed/, not the test fixture) names place_wire_hold's approving team, so the
    review service refuses an approver from any other team."""
    tenant = f"t_{uuid4().hex[:10]}"
    seed = json.loads((Path(__file__).parents[1] / "seed" / "tool_modules.json").read_text())
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    found = await ModuleStore(engine).operation_named(tenant, "place_wire_hold")
    assert found is not None
    module, op = found
    assert approval_policy(module, op) == {
        "approvers": 2,
        "approver_team": "team_fraud",
        "step_up": True,
    }
