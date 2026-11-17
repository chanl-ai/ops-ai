"""A module's published copy (`baseline`) written before the typed aggregate: no headers and none of the columns added
since, its amount as text. It loads, its operation is served from it, a call's amount limit reads the text, and a save
writes the copy back exactly as stored."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa

from ops_service_kit.http import JsonValue
from ops_store.team_scope import acting_as
from ops_tools.limits import Refusal, amount_refusal
from ops_tools.modules.seed import blank
from ops_tools.store.modules import (
    ModuleStore,
    Operation,
    module_operations,
    operation_defaults,
    served_operations,
    tool_modules,
)

TEAM = "team_a"
# The operation as a publish before the typed aggregate copied it: no `headers`, `body_encoding`, `response_transform`,
# `timeout_ms`, `approval_mode`, `needs_person`, `step_up`, `approver_team` or `scopes`, and the limit as text.
OLD_COPY: dict[str, JsonValue] = {
    "id": "mod_old_op1",
    "tool_id": "tl_pay",
    "name": "pay_invoice",
    "description": "Pays an invoice",
    "access": "write",
    "enabled": True,
    "executor": "stub",
    "method": "POST",
    "path": "/v1/payments",
    "body": None,
    "input": [{"name": "amount", "type": "number", "required": True}],
    "masked_output": [],
    "binding": None,
    "rate_limit_per_min": 60,
    "requires_approval": False,
    "amount_max": "250.00",
    "approvers": 1,
    "stub": {"ok": True},
}


def _operation() -> Operation:
    """The operation as edited since publish: a new path and a higher limit, neither served until publish."""
    return {
        **operation_defaults(),
        "id": "mod_old_op1",
        "tool_id": "tl_pay",
        "name": "pay_invoice",
        "description": "Pays an invoice",
        "access": "write",
        "enabled": True,
        "executor": "stub",
        "method": "POST",
        "path": "/v2/payments",
        "headers": [{"key": "X-Trace", "value": "on"}],
        "body": None,
        "input": [{"name": "amount", "type": "number", "required": True}],
        "masked_output": [],
        "binding": None,
        "rate_limit_per_min": 60,
        "requires_approval": False,
        "amount_max": Decimal("900"),
        "stub": {"ok": True},
    }


async def _stored_copy(store: ModuleStore, tenant: str) -> str:
    async with store.tx() as c:
        q = sa.select(tool_modules.c.baseline).where(tool_modules.c.tenant_id == tenant, tool_modules.c.id == "mod_old")
        return json.dumps((await c.execute(q)).scalar_one())


async def test_an_old_published_copy_is_served_limits_calls_and_is_written_back_as_stored(
    store: ModuleStore, tenant: str
) -> None:
    now = datetime.now(UTC)
    m = blank(
        module_id="mod_old",
        tenant_id=tenant,
        team_id=TEAM,
        owner="Ops",
        me="seed",
        at=now,
        input={"displayName": "Payables", "name": "payables", "type": "http"},
    )
    await store.put(
        {**m, "status": "published", "operations": [_operation()], "baseline": [OLD_COPY]}, expected_revision=None
    )
    with acting_as(TEAM):
        written = await _stored_copy(store, tenant)
        held = await store.get(tenant, "mod_old")
        assert held is not None
        [served] = served_operations(held)
        # Served from the copy: its path, no headers (the copy names none) and its limit as a number.
        assert (served["path"], served["headers"], served["amount_max"]) == ("/v1/payments", [], Decimal("250.00"))
        assert amount_refusal(served, {"amount": 300}) == Refusal(
            403, "amount_over_limit", "amount 300 is over pay_invoice's limit of 250.00"
        )
        assert amount_refusal(served, {"amount": 250}) is None
        found = await store.operation_named(tenant, "pay_invoice")
        assert found is not None and found[1]["path"] == "/v1/payments"
        # A save of what was read leaves the stored copy as it was, key for key and in order.
        await store.put(held, expected_revision=held["revision"])
        assert await _stored_copy(store, tenant) == written == json.dumps([OLD_COPY])


# An input field as the request model saved it: every optional key named, unset ones null (found in stored rows).
SAVED_FIELD: dict[str, JsonValue] = {
    "name": "document",
    "type": "object",
    "required": True,
    "description": None,
    "format": None,
    "enum": None,
    "example": None,
    "default": None,
}


async def test_an_input_field_saved_with_null_optional_keys_loads_and_is_written_back(
    store: ModuleStore, tenant: str
) -> None:
    m = blank(
        module_id="mod_old",
        tenant_id=tenant,
        team_id=TEAM,
        owner="Ops",
        me="seed",
        at=datetime.now(UTC),
        input={"displayName": "Payables", "name": "payables", "type": "http"},
    )
    await store.put({**m, "operations": [_operation()]}, expected_revision=None)
    with acting_as(TEAM):
        o = module_operations.c
        async with store.tx() as c:
            await c.execute(
                module_operations.update()
                .where(o.tenant_id == tenant, o.module_id == "mod_old")
                .values(input=[SAVED_FIELD])
            )
        held = await store.get(tenant, "mod_old")
        assert held is not None and held["operations"][0]["input"] == [SAVED_FIELD]
        await store.put(held, expected_revision=held["revision"])
        async with store.tx() as c:
            stored = (
                await c.execute(sa.select(o.input).where(o.tenant_id == tenant, o.module_id == "mod_old"))
            ).scalar_one()
        assert json.dumps(stored) == json.dumps([SAVED_FIELD])
