"""Which account a call signs in with, by failure mode: a test run on an app connected only for production is refused
for want of a test account (the agent's Test panel could not call a tool after one Connect); a test run's write on the
production account changes live data with nobody asked; and a live run falls back to a test account."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.contract import response_checker
from ops_service_kit.ids import new_id
from ops_store import isolation
from ops_tools.connections.records import slot_for
from ops_tools.modules.seed import load, open_connection
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.egress import EgressStore
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, opa_client, service_headers
from .fake_upstream import ENDPOINT, HOST, SlowAware, fake_bank
from .test_calls import bank_module

ACCOUNT = {"accountId": "CHQ-2219"}
HOLD = {"accountId": "CHQ-2219", "hours": 24}


def test_a_test_run_uses_the_test_account_else_production_and_a_live_run_only_production() -> None:
    assert slot_for({"test": {}, "production": {}}, "test") == "test"
    assert slot_for({"production": {}}, "test") == "production"
    assert slot_for({"test": {}}, "production") is None
    assert slot_for({}, "test") is None


async def _module_on(engine: AsyncEngine, tenant: str, suffix: str, environments: tuple[str, ...]) -> None:
    module = bank_module(tenant, suffix)
    # The hold runs without an approval of its own, so only the account it signs in with can make it wait.
    module["operations"] = [
        {**o, "requires_approval": False} if o["name"].startswith("place_hold") else o for o in module["operations"]
    ]
    now = datetime.now(UTC)
    row, envs = open_connection(
        tenant_id=tenant, team_id=module["team_id"], connection_id=f"con_{module['id']}",
        name=module["display_name"], base=ENDPOINT, me="test", at=now,
    )  # fmt: skip
    kept = {e: v for e, v in envs.items() if e in environments}
    with isolation.scope(tenant, module["team_id"]):
        await ConnectionStore(engine).create(row, actor="test", at=now, environments=kept)
    await ModuleStore(engine).put({**module, "connection_id": row["id"]}, expected_revision=None)


Call = Any


@pytest.fixture
def gateway_on(engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]):
    async def made(environments: tuple[str, ...]) -> AsyncIterator[Call]:
        await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
        suffix = new_id("x")[2:8].lower()
        await EgressStore(engine).add(tenant, "host", HOST, actor="test", note="", at=datetime.now(UTC))
        await _module_on(engine, tenant, suffix, environments)
        bank, _ = fake_bank()
        async with (
            opa_client() as opa,
            httpx.AsyncClient(transport=SlowAware(httpx.ASGITransport(app=bank))) as upstream,
        ):
            app = build_app(engine, seed, tenant, opa=opa, upstream=upstream)
            hooks = {"response": [response_checker(app)]}
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
                ) as c,
            ):

                async def call(base: str, args: dict[str, Any], run: str, step: str) -> httpx.Response:
                    body = {
                        "tool": f"{base}_{suffix}",
                        "input": args,
                        "key": step,
                        "runContext": {"thread": "t-run", "step": step, "act": "test", "environment": run},
                    }
                    return await c.post("/v1/calls", json=body, headers=service_headers(tenant))

                yield call

    return made


async def test_a_test_run_on_an_app_connected_only_for_production_reads_with_that_account(gateway_on: Any) -> None:
    async for call in gateway_on(("production",)):
        r = await call("get_account", ACCOUNT, "test", "r1")
        assert r.status_code == 200 and r.json()["data"]["ok"] is True, r.text


async def test_a_test_runs_write_on_the_production_account_waits_for_a_person(gateway_on: Any) -> None:
    async for call in gateway_on(("production",)):
        held = await call("place_hold", HOLD, "test", "w1")
        assert held.status_code == 403, held.text
        assert held.json()["error"]["details"]["reasons"] == ["write needs an approval token"], held.text
        live = await call("place_hold", HOLD, "production", "w2")
        assert live.status_code == 200 and live.json()["data"]["ok"] is True, live.text


async def test_a_test_runs_write_on_a_test_account_runs(gateway_on: Any) -> None:
    async for call in gateway_on(("test", "production")):
        r = await call("place_hold", HOLD, "test", "w3")
        assert r.status_code == 200 and r.json()["data"]["ok"] is True, r.text


async def test_a_live_run_never_signs_in_with_the_test_account(gateway_on: Any) -> None:
    async for call in gateway_on(("test",)):
        r = await call("get_account", ACCOUNT, "production", "r2")
        out = r.json()["data"]
        assert out["ok"] is False and out["output"]["error"]["code"] == "CONNECTION_NOT_SET", r.text
