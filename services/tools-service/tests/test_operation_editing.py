"""Editing an operation's input, access and the secrets it reads (c-073), by failure mode: a new required field or a
removed one slipping in as a minor version, a field a binding or the call uses removed, a schema no call could honour
saved, a `{{SECRET}}` in the path becoming an input an agent fills, an access change staged as minor, a default the
agent is promised but the system never receives, and a secret the operation reads that nobody set."""

from __future__ import annotations

from typing import Any

import httpx

from .conftest import Api, service_headers

MOD = "/mod_core_banking"


async def _ok(r: httpx.Response) -> Any:
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _op(api: Api, name: str) -> dict[str, Any]:
    detail = await _ok(await api.call("GET", MOD))
    return next(o for o in detail["operations"] if o["name"] == name)


def _fields(op: dict[str, Any]) -> list[dict[str, Any]]:
    return [{k: v for k, v in f.items() if v is not None} for f in op["input"]]


async def _patch(api: Api, op: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
    return await api.call("PATCH", f"{MOD}/operations/{op['id']}", json=body)


def _change(detail: dict[str, Any], name: str) -> dict[str, Any]:
    return next(c for c in detail["pendingChanges"] if c["operation"] == name and c["kind"] == "schema_changed")


async def test_a_new_required_field_is_major_and_a_new_optional_one_minor(api: Api) -> None:
    op = await _op(api, "get_customer_profile")
    optional = await _ok(
        await _patch(api, op, {"input": [*_fields(op), {"name": "locale", "type": "string", "required": False}]})
    )
    assert _change(optional, "get_customer_profile")["major"] is False
    required = [*_fields(op), {"name": "branch", "type": "string", "required": True}]
    staged = await _ok(await _patch(api, op, {"input": required}))
    change = _change(staged, "get_customer_profile")
    assert change["major"] is True and "branch added (required)" in change["detail"], change


async def test_a_description_only_edit_publishes_as_a_minor_version(api: Api) -> None:
    detail = await _ok(await api.call("GET", MOD))
    op = next(o for o in detail["operations"] if o["name"] == "get_customer_profile")
    fields = [{**f, "description": "The customer's id in core banking"} for f in _fields(op)]
    await _ok(await _patch(api, op, {"input": fields}))
    published = await _ok(await api.call("POST", f"{MOD}/versions", json={"note": "Clearer field text"}))
    a, b, _ = detail["version"].split(".")
    assert published["version"] == f"{a}.{int(b) + 1}.0", "nothing an agent may send changed"


async def test_removing_a_field_the_binding_or_the_amount_limit_uses_is_refused_naming_it(api: Api) -> None:
    op = await _op(api, "get_loan_account")
    gone = await _patch(api, op, {"input": [f for f in _fields(op) if f["name"] != "loanAccountId"]})
    assert gone.status_code == 422, gone.text
    error = gone.json()["error"]
    assert "case.account" in error["message"] and error["details"]["field"] == "input.loanAccountId", error


async def test_a_schema_no_call_could_honour_is_refused_naming_the_field(api: Api) -> None:
    op = await _op(api, "get_customer_profile")
    base = _fields(op)
    cases = {
        "default_type": {"name": "limit", "type": "integer", "required": False, "default": "ten"},
        "default_required": {"name": "limit", "type": "integer", "required": True, "default": 10},
        "enum_on_number": {"name": "limit", "type": "integer", "required": False, "enum": ["1", "2"]},
        "default_outside_enum": {"name": "tier", "type": "string", "required": False, "enum": ["a"], "default": "b"},
        "bad_name": {"name": "has space", "type": "string", "required": False},
    }
    for case, field in cases.items():
        r = await _patch(api, op, {"input": [*base, field]})
        assert r.status_code == 422, (case, r.text)
        assert r.json()["error"]["details"]["field"] == f"input.{field['name']}", (case, r.text)
    twice = await _patch(api, op, {"input": [*base, base[0]]})
    assert twice.status_code == 422 and "twice" in twice.json()["error"]["message"]


async def _http_op(api: Api, name: str) -> dict[str, Any]:
    """An HTTP operation built in the module, since the seeded ones answer from stubs and take no call shape."""
    detail = await _ok(await api.call("GET", MOD))
    url = detail["endpoint"].rstrip("/") + "/rates/{currency}"
    body = {"name": name, "description": "A rate", "access": "read", "method": "GET", "url": url}
    made = await _ok(await api.call("POST", f"{MOD}/operations", json=body))
    return next(o for o in made["operations"] if o["name"] == name)


async def test_a_secret_in_the_path_is_never_an_input_and_a_missing_argument_is_refused(api: Api) -> None:
    op = await _http_op(api, "get_rate")
    keyed = await _ok(await _patch(api, op, {"path": "/rates/{currency}?api_key={{RATES_KEY}}"}))
    names = [f["name"] for f in next(o for o in keyed["operations"] if o["name"] == "get_rate")["input"]]
    assert names == ["currency"], "the secret the URL reads is not something an agent sends"
    unknown = await _patch(api, op, {"path": "/rates/{currency}/{day}?api_key={{RATES_KEY}}", "input": _fields(op)})
    assert unknown.status_code == 422 and unknown.json()["error"]["details"]["field"] == "input.day", unknown.text


async def test_an_access_change_is_major_and_carries_the_approval_with_it(api: Api) -> None:
    op = await _op(api, "get_payoff_statement")
    staged = await _ok(await _patch(api, op, {"access": "write"}))
    change = next(c for c in staged["pendingChanges"] if c["operation"] == "get_payoff_statement")
    assert change == {**change, "kind": "access_widened", "major": True}
    after = next(o for o in staged["operations"] if o["name"] == "get_payoff_statement")
    assert (after["access"], after["requiresApproval"]) == ("write", True)


async def test_a_default_reaches_the_agents_schema_once_published(api: Api) -> None:
    op = await _op(api, "update_address")
    fields = [{**f, "default": "Unit 1"} if f["name"] == "line2" else f for f in _fields(op)]
    await _ok(await _patch(api, op, {"input": fields}))
    await _ok(await api.call("POST", f"{MOD}/versions", json={"note": "Default line2"}))
    # A default changes what a read sends, so the version waits for Security; it is served once approved.
    await _ok(await api.decide(MOD))
    served = await _ok(await api.client.get("/v1/grantable-operations", headers=service_headers(api.tenant)))
    schema = next(o for o in served if o["name"] == "update_address")["inputSchema"]
    assert schema["properties"]["line2"]["default"] == "Unit 1", schema


async def test_the_secrets_an_operation_reads_show_whether_they_are_set(api: Api) -> None:
    op = await _http_op(api, "get_rate_keyed")
    await _ok(await _patch(api, op, {"headers": [{"key": "X-Api-Key", "value": "{{CORE_KEY}}"}]}))
    before = await _ok(await api.call("GET", MOD))
    assert next(o for o in before["operations"] if o["id"] == op["id"])["secrets"] == [
        {"name": "CORE_KEY", "set": False, "available": False}
    ]
    assert before["unsetSecrets"] == 1
    listed = await _ok(await api.call("GET", ""))
    assert next(r for r in listed["data"] if r["id"] == "mod_core_banking")["unsetSecrets"] == 1
    await api.client.post("/v1/secrets", json={"name": "CORE_KEY", "value": "k-123"})
    after = await _ok(await api.call("GET", MOD))
    assert next(o for o in after["operations"] if o["id"] == op["id"])["secrets"] == [
        {"name": "CORE_KEY", "set": True, "available": True}
    ]
    assert after["unsetSecrets"] == 0


async def test_a_type_allowed_values_default_or_removed_field_change_is_major(api: Api) -> None:
    """Each changes what a call sends or may send, so Security reviews it (a default is sent for the agent on reads)."""
    op = await _op(api, "update_address")
    base = _fields(op)
    edits = {
        "type": [{**f, "type": "integer"} if f["name"] == "line2" else f for f in base],
        "allowed values": [{**f, "enum": ["A", "B"]} if f["name"] == "line2" else f for f in base],
        "default": [{**f, "default": "Unit 1"} if f["name"] == "line2" else f for f in base],
        "removed": [f for f in base if f["name"] != "line2"],
    }
    for what, fields in edits.items():
        staged = await _ok(await _patch(api, op, {"input": fields}))
        assert _change(staged, "update_address")["major"] is True, what
        await _ok(await api.call("DELETE", f"{MOD}/pending-changes"))
