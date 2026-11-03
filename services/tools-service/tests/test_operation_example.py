"""An operation's example answer is its default mock, by failure mode: the example and the mocks are two
homes that disagree, so Mock answers one thing and the mock list shows another; a mock made for one team's operation
answers another team's operation of the same name; and a system with no upstream stops answering in production once
its example moves to a test-only mock."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_tools.mocks import MockAnswers
from ops_tools.modules.seed import blank
from ops_tools.store.mocks import MockStore
from ops_tools.store.modules import ModuleStore

from .test_calls import MODULE, Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_registry_store import _alembic, scratch_database  # pyright: ignore[reportPrivateUsage]

TEAM = {"X-Team-Id": "team_platform"}
OP = f"{MODULE}_op1"
OPERATION: dict[str, Any] = {
    "id": "mod_example_op1", "tool_id": "tl_read_example", "name": "read_example", "description": "Reads.",
    "access": "read", "enabled": True, "executor": "http", "method": "GET", "path": "/example", "headers": [],
    "body": None, "input": [], "masked_output": [], "binding": None, "rate_limit_per_min": 60,
    "requires_approval": False, "amount_max": None,
}  # fmt: skip


async def test_the_example_is_one_answer_that_never_holds_back_a_real_run(gateway: Gateway) -> None:  # noqa: F811
    base = f"/v1/tool-modules/{MODULE}"
    edited = await gateway.client.patch(f"{base}/operations/{OP}", json={"stub": {"balance": 1}}, headers=TEAM)
    assert edited.status_code == 200, edited.text
    path = f"{base}/operations/{OP}/mocks"
    listed = (await gateway.client.get(path, params={"environment": "example"}, headers=TEAM)).json()["data"]["data"]
    assert [(m["default"], m["body"]) for m in listed] == [(True, {"balance": 1})], listed
    body = {"name": "Rich", "environment": "example", "default": True, "body": {"balance": 9}}
    assert (await gateway.client.post(path, json=body, headers=TEAM)).status_code == 201
    detail = (await gateway.client.get(base, headers=TEAM)).json()["data"]
    assert next(o for o in detail["operations"] if o["id"] == OP)["stub"] == {"balance": 9}
    run = f"{base}/operations/{gateway.tool('get_account')}/run"
    mocked = await gateway.client.post(run, json={"mode": "mock", "input": {"accountId": "A"}}, headers=TEAM)
    assert mocked.json()["data"]["output"] == {"balance": 9}, mocked.text
    # An example is not a test mock: a Real run in test still reaches the system.
    real = await gateway.client.post(run, json={"mode": "real", "input": {"accountId": "A"}}, headers=TEAM)
    assert real.json()["data"]["mocked"] is False and [x["path"] for x in gateway.received] == ["/v1/accounts/A"]


async def test_a_mock_answers_only_its_own_modules_operation(engine: AsyncEngine, tenant: str) -> None:
    store = MockStore(engine)
    now = datetime.now(UTC)
    row = {
        "tenant_id": tenant, "id": "mck_a", "module_id": "mod_team_a", "operation": "lookup", "environment": "test",
        "name": "A", "match": {}, "status": 200, "body": {"team": "a"}, "headers": {}, "delay_ms": 0,
        "timeout": False, "is_default": True, "from_call_id": None, "created_by": "t", "created_at": now,
        "updated_at": now,
    }  # fmt: skip
    await store.add(row)
    answers = MockAnswers(store)
    assert (await answers.for_call(tenant, "mod_team_a", "lookup", {}, "test") or {}).get("body") == {"team": "a"}
    assert await answers.for_call(tenant, "mod_team_b", "lookup", {}, "test") is None


async def test_a_system_with_no_upstream_answers_its_example_in_production(
    gateway: Gateway,  # noqa: F811
    engine: AsyncEngine,
) -> None:
    store = ModuleStore(engine)
    m = await store.get(gateway.tenant, MODULE)
    assert m is not None
    ops = [
        {**o, "executor": "stub", "stub": {"held": True}} if o["id"] == f"{MODULE}_op3" else o for o in m["operations"]
    ]
    await store.put({**m, "operations": ops}, expected_revision=m["revision"])
    r = await gateway.call("limited", {}, step="s1")
    out = r.json()["data"]
    assert (out["ok"], out["output"]) == (True, {"held": True}), out


async def test_the_downgrade_puts_each_example_back_on_its_operation() -> None:
    # Every migration has a real downgrade (kaizen 10-31): down and up again keeps each example where its code reads it.
    async with scratch_database("tools_examples") as target:
        _alembic(target, "upgrade", "head")
        engine = create_async_engine(target)
        try:
            m = blank(
                module_id="mod_example", tenant_id="t_ex", team_id="team_ops", owner="Operations", me="t",
                at=datetime.now(UTC), input={"displayName": "Example", "name": "example", "type": "http"},
            )  # fmt: skip
            m["operations"] = [{**OPERATION, "stub": {"balance": 3}}]
            await ModuleStore(engine).put(m, expected_revision=None)
            _alembic(target, "downgrade", "tools_0052_reconnect_notice")
            async with engine.connect() as c:
                stub = (
                    await c.execute(sa.text("select stub from module_operations where module_id = 'mod_example'"))
                ).scalar()
                left = (
                    await c.execute(sa.text("select count(*) from operation_mocks where environment = 'example'"))
                ).scalar()
            assert (stub, left) == ({"balance": 3}, 0)
            _alembic(target, "upgrade", "head")
            assert (await ModuleStore(engine).get("t_ex", "mod_example") or {})["operations"][0]["stub"] == {
                "balance": 3
            }
        finally:
            await engine.dispose()


async def test_mock_answers_the_example_as_the_tools_output_without_its_transform(gateway: Gateway) -> None:  # noqa: F811
    # The example is what the tool gives back, already shaped: the transform reads the system's raw answer, which a
    # Mock run never has, so applying it to the example failed (PM walk, 2026-11-01).
    base = f"/v1/tool-modules/{MODULE}"
    shaped = {"responseTransform": '{"fields": {{ data.fields | length }}}', "stub": {"fields": 3}}
    edited = await gateway.client.patch(f"{base}/operations/{OP}", json=shaped, headers=TEAM)
    assert edited.status_code == 200, edited.text
    run = f"{base}/operations/{gateway.tool('get_account')}/run"
    mocked = (await gateway.client.post(run, json={"mode": "mock", "input": {"accountId": "A"}}, headers=TEAM)).json()
    assert mocked["data"]["output"] == {"fields": 3} and "transformError" not in mocked["data"], mocked
