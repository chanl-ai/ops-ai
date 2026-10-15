"""The write approval policy per operation (c-048 T005), by failure mode: a policy no reviewer could satisfy saved, a
money operation left with one approver, an approving team that does not exist, and a loosened policy taking effect
before Security reviews it. OPA's side, a token with too few approvers, is in test_calls.py."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

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
    assert (op["approvers"], op["selfApproval"]) == (1, False)
    assert str(op["approverTeam"]).startswith("team_"), detail["ownerTeam"]
    assert await _policy(api, "update_address") == {
        "approvers": 1,
        "approverTeam": op["approverTeam"],
        "selfApproval": False,
    }


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
    staged = await _ok(await api.call("PATCH", f"/mod_core_banking/operations/{op['id']}", json={"selfApproval": True}))
    assert staged["pendingChanges"][0]["major"] is True
    assert (await _policy(api, "update_address"))["selfApproval"] is False, "staged, not applied"
    review = await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Askers approve"}))
    assert review["versions"][0]["status"] == "in_review"
    assert (await _policy(api, "update_address"))["selfApproval"] is False, "the published policy holds during review"
    pending = next(r["id"] for r in review["reviews"] if r["decision"] == "pending")
    decide = f"/mod_core_banking/reviews/{pending}/decide"
    await _ok(await api.call("POST", decide, user="Nadia Petrov", json={"decision": "approved"}))
    assert (await _policy(api, "update_address"))["selfApproval"] is True, "applied once Security approved"


async def test_nothing_is_edited_or_published_while_a_version_waits_for_security(api: Api) -> None:
    """An edit or a version on top of one in review would leave Security approving something that is no longer what
    calls switch to, so the reviewed policy could never apply as reviewed."""
    op = await _op(api, "mod_core_banking", "update_address")
    path = f"/mod_core_banking/operations/{op['id']}"
    await _ok(await api.call("PATCH", path, json={"selfApproval": True}))
    major = await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Askers approve"}))
    edit = await api.call("PATCH", path, json={"description": "Change a customer's mailing address"})
    assert edit.status_code == 409, edit.text
    minor = await api.call("POST", "/mod_core_banking/versions", json={"note": "Wording"})
    assert minor.status_code in (400, 409), minor.text
    assert (await _policy(api, "update_address"))["selfApproval"] is False
    pending = next(r["id"] for r in major["reviews"] if r["decision"] == "pending")
    decide = f"/mod_core_banking/reviews/{pending}/decide"
    await _ok(await api.call("POST", decide, user="Nadia Petrov", json={"decision": "approved"}))
    assert (await _policy(api, "update_address"))["selfApproval"] is True, "Security's approval takes effect"
    assert (
        await api.call("PATCH", path, json={"description": "Change a customer's mailing address"})
    ).status_code == 200


async def _loosen_and_request(api: Api) -> tuple[str, dict[str, Any]]:
    op = await _op(api, "mod_core_banking", "update_address")
    path = f"/mod_core_banking/operations/{op['id']}"
    await _ok(await api.call("PATCH", path, json={"selfApproval": True}))
    return path, await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Askers approve"}))


async def test_no_operation_is_added_or_discarded_while_a_version_waits_for_security(api: Api) -> None:
    _, major = await _loosen_and_request(api)
    endpoint = major["endpoint"].rstrip("/")
    new = {"name": "close_account_t017", "description": "", "access": "write", "method": "POST", "url": f"{endpoint}/x"}
    assert (await api.call("POST", "/mod_core_banking/operations", json=new)).status_code == 409
    assert (await api.call("DELETE", "/mod_core_banking/pending-changes")).status_code == 409
    pending = next(r["id"] for r in major["reviews"] if r["decision"] == "pending")
    await _ok(
        await api.call(
            "POST", f"/mod_core_banking/reviews/{pending}/decide", user="Nadia Petrov", json={"decision": "approved"}
        )
    )
    assert (await _policy(api, "update_address"))["selfApproval"] is True, "the approved version applies"


async def test_changes_requested_ends_the_review_and_unlocks_edits(api: Api) -> None:
    path, major = await _loosen_and_request(api)
    pending = next(r["id"] for r in major["reviews"] if r["decision"] == "pending")
    decided = await _ok(
        await api.call(
            "POST",
            f"/mod_core_banking/reviews/{pending}/decide",
            user="Nadia Petrov",
            json={"decision": "changes_requested", "findings": ["Askers must not approve their own writes"]},
        )
    )
    assert not any(v["status"] == "in_review" for v in decided["versions"])
    assert (await _policy(api, "update_address"))["selfApproval"] is False, "the declined policy never applies"
    assert (await api.call("PATCH", path, json={"selfApproval": False})).status_code == 200


async def test_a_declined_change_never_goes_live_by_a_later_minor_edit(api: Api) -> None:
    path, major = await _loosen_and_request(api)
    pending = next(r["id"] for r in major["reviews"] if r["decision"] == "pending")
    await _ok(
        await api.call(
            "POST",
            f"/mod_core_banking/reviews/{pending}/decide",
            user="Nadia Petrov",
            json={"decision": "changes_requested", "findings": ["Askers must not approve their own writes"]},
        )
    )
    await _ok(await api.call("PATCH", path, json={"description": "Change a customer's mailing address"}))
    again = await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Wording"}))
    assert again["versions"][0]["status"] == "in_review", "the declined policy still differs, so this is major"
    assert (await _policy(api, "update_address"))["selfApproval"] is False


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
    major = await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Bigger transfers"}))
    pending = next(r["id"] for r in major["reviews"] if r["decision"] == "pending")
    await _ok(
        await api.call(
            "POST",
            f"/mod_core_banking/reviews/{pending}/decide",
            user="Nadia Petrov",
            json={"decision": "changes_requested", "findings": ["Keep the limit and the binding"]},
        )
    )
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
        listed = await api.client.get("/v1/internal/operations", headers=service_headers(api.tenant))
        names = {o["name"] for o in listed.json()["data"]}
        resolved = await ModuleStore(engine).operation_named(api.tenant, "close_account_zz")
        assert (tool.status_code == 200) == ("close_account_zz" in names) == (resolved is not None)
        return resolved is not None

    assert not await served(), "staged: not served, listed or grantable"
    major = await _ok(await api.call("POST", "/mod_core_banking/versions", json={"note": "Close accounts"}))
    assert not await served(), "in review: still not served"
    pending = next(r["id"] for r in major["reviews"] if r["decision"] == "pending")
    await _ok(
        await api.call(
            "POST", f"/mod_core_banking/reviews/{pending}/decide", user="Nadia Petrov", json={"decision": "approved"}
        )
    )
    assert await served(), "served once Security approved"
