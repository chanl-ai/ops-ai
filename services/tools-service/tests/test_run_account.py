"""Which account a call signs in with, by failure mode: a test run on an app with only its live account is refused
(the agent's Test panel could not call a tool after one Connect); a test run's write on the live account changes live
data with nobody asked; a test run ignores the app's sandbox account; and a live run signs in with a sandbox."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import dev_service_signer, mint_service_token
from ops_service_kit.contract import response_checker
from ops_service_kit.ids import new_id
from ops_store import isolation
from ops_tools.connections.records import account_for
from ops_tools.modules.seed import load, open_connection
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.egress import EgressStore
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, opa_client, service_headers
from .fake_upstream import ENDPOINT, HOST, SlowAware, fake_bank
from .test_calls import bank_module
from .test_write_approval_gateway import TeamAsksReviewer

ACCOUNT = {"accountId": "CHQ-2219"}
HOLD = {"accountId": "CHQ-2219", "hours": 24}


def test_a_test_run_uses_the_sandbox_account_else_the_default_and_a_live_run_the_default() -> None:
    live, sandbox = {"id": "live", "sandbox": False}, {"id": "sbx", "sandbox": True}
    assert account_for(live, [live, sandbox], "test") == sandbox
    assert account_for(live, [live], "test") == live
    assert account_for(live, [live, sandbox], "live") == live
    assert account_for(None, [], "test") is None


async def _module_on(engine: AsyncEngine, tenant: str, suffix: str, accounts: tuple[str, ...]) -> None:
    """The module on its app's accounts: `live` its first account, `sandbox` a sandbox one beside it; with only a
    sandbox, the app's first account is the sandbox."""
    module = bank_module(tenant, suffix)
    # The hold runs without an approval of its own, so only the account it signs in with can make it wait.
    module["operations"] = [
        {**o, "requires_approval": False} if o["name"].startswith("place_hold") else o for o in module["operations"]
    ]
    now = datetime.now(UTC)
    row = open_connection(
        tenant_id=tenant, team_id=module["team_id"], connection_id=f"con_{module['id']}",
        name=module["display_name"], base=ENDPOINT, me="test", at=now,
    )  # fmt: skip
    with isolation.scope(tenant, module["team_id"]):
        await ConnectionStore(engine).create({**row, "sandbox": "live" not in accounts}, actor="test", at=now)
        if "live" in accounts and "sandbox" in accounts:
            other = {**row, "id": f"{row['id']}_sbx", "sandbox": True, "account_name": "Sandbox"}
            await ConnectionStore(engine).create(other, actor="test", at=now)
    await ModuleStore(engine).put({**module, "connection_id": row["id"]}, expected_revision=None)


Call = Any


@pytest.fixture
def gateway_on(engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]):
    async def made(accounts: tuple[str, ...], approvals: Any = None) -> AsyncIterator[Call]:
        await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
        suffix = new_id("x")[2:8].lower()
        await EgressStore(engine).add(tenant, "host", HOST, actor="test", note="", at=datetime.now(UTC))
        await _module_on(engine, tenant, suffix, accounts)
        bank, _ = fake_bank()
        async with (
            opa_client() as opa,
            httpx.AsyncClient(transport=SlowAware(httpx.ASGITransport(app=bank))) as upstream,
        ):
            app = build_app(engine, seed, tenant, opa=opa, upstream=upstream, write_approvals=approvals)
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


async def test_a_test_run_on_an_app_with_only_its_live_account_reads_with_that_account(gateway_on: Any) -> None:
    async for call in gateway_on(("live",)):
        r = await call("get_account", ACCOUNT, "test", "r1")
        assert r.status_code == 200 and r.json()["data"]["ok"] is True, r.text


async def test_a_test_runs_write_on_the_live_account_follows_the_rules_a_live_one_does(gateway_on: Any) -> None:
    # The app's "Ask before changes" asks the person in chat; the gateway adds no hold of its own for a test run.
    async for call in gateway_on(("live",)):
        tested = await call("place_hold", HOLD, "test", "w1")
        assert tested.status_code == 200 and tested.json()["data"]["ok"] is True, tested.text
        live = await call("place_hold", HOLD, "live", "w2")
        assert live.status_code == 200 and live.json()["data"]["ok"] is True, live.text


async def test_a_write_on_the_test_account_never_waits_whatever_the_team_holds(gateway_on: Any) -> None:
    # A test account changes nothing real: a team that has every write wait still lets it run, and a live one waits.
    async for call in gateway_on(("live", "sandbox"), TeamAsksReviewer()):
        r = await call("place_hold", HOLD, "test", "w4")
        assert r.status_code == 200 and r.json()["data"]["ok"] is True, r.text
        live = await call("place_hold", HOLD, "live", "w5")
        assert live.status_code == 403, live.text


async def test_a_test_runs_write_on_the_sandbox_account_runs(gateway_on: Any) -> None:
    async for call in gateway_on(("live", "sandbox")):
        r = await call("place_hold", HOLD, "test", "w3")
        assert r.status_code == 200 and r.json()["data"]["ok"] is True, r.text


async def test_a_live_run_never_signs_in_with_a_sandbox_account(gateway_on: Any) -> None:
    async for call in gateway_on(("sandbox",)):
        r = await call("get_account", ACCOUNT, "live", "r2")
        out = r.json()["data"]
        assert out["ok"] is False and out["output"]["error"]["code"] == "CONNECTION_NOT_SET", r.text


@pytest.mark.parametrize(("accounts", "told"), [(("live", "sandbox"), True), (("live",), False)])
async def test_agents_are_told_which_apps_write_to_a_test_account_so_chat_never_asks_there(  # noqa: PLR0917
    engine: AsyncEngine,
    seed: dict[str, Any],
    tenant: str,
    catalog_tools: list[dict[str, Any]],
    accounts: tuple[str, ...],
    told: bool,
) -> None:
    # The grantable operations say whether the app has a test account for the team: a test run's write there changes
    # nothing real, so agents-service does not ask the person first; an app with only its live account still asks.
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    suffix = new_id("x")[2:8].lower()
    await EgressStore(engine).add(tenant, "host", HOST, actor="test", note="", at=datetime.now(UTC))
    await _module_on(engine, tenant, suffix, accounts)
    async with opa_client() as opa:
        app = build_app(engine, seed, tenant, opa=opa, write_approvals=TeamAsksReviewer())
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c,
        ):
            team = bank_module(tenant, suffix)["team_id"]
            token = mint_service_token(
                dev_service_signer(), service="agents", audience="tools", tenant_id=tenant, team_id=team,
                scopes=["tools:view"],
            )  # fmt: skip
            r = await c.get("/v1/grantable-operations", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200, r.text
            row = next(o for o in r.json()["data"] if o["name"] == f"place_hold_{suffix}")
    assert row["testAccount"] is told, row
