"""The tool workbench's runs (c-088), by failure mode: a draft transform or mock reaching what agents get before it is
staged, a transform failure with no reason or a blank answer, a value typed for a secret being stored, logged or shown,
and an edited mock skipping review."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.contract import response_checker
from ops_service_kit.ids import new_id
from ops_tools.modules.seed import load
from ops_tools.store.egress import EgressStore
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, opa_client
from .fake_upstream import HOST, SlowAware, fake_bank
from .test_calls import MODULE, Gateway, bank_module

BASE = f"/v1/tool-modules/{MODULE}"
# A value no other row in the test database holds, so finding it anywhere means this run stored it.
TYPED = f"typed-{new_id('k')}-value"


async def _gateway(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], path: str
) -> AsyncIterator[Gateway]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    suffix = new_id("x")[2:8].lower()
    module = bank_module(tenant, suffix)
    read = module["operations"][0]
    read["path"] = path
    read["headers"] = [{"key": "X-Api-Key", "value": "{{WB_BANK_KEY}}"}]
    await EgressStore(engine).add(tenant, "host", HOST, actor="test", note="", at=datetime.now(UTC))
    await ModuleStore(engine).put(module, expected_revision=None)
    bank, received = fake_bank()
    async with (
        opa_client() as opa,
        httpx.AsyncClient(transport=SlowAware(httpx.ASGITransport(app=bank))) as upstream,
    ):
        app = build_app(engine, seed, tenant, opa=opa, upstream=upstream)
        hooks = {"response": [response_checker(app)]}
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks) as c,
        ):
            yield Gateway(c, received, suffix, new_id("gth"), tenant)


@pytest.fixture
async def g(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Gateway]:
    """The bank module of test_calls, its account read sending the key the tenant has not set, in a header and the
    query, as the core bank's statement route does."""
    path = "/accounts/{accountId}?api_key={{WB_BANK_KEY}}"
    async for gateway in _gateway(engine, seed, tenant, catalog_tools, path):
        yield gateway


@pytest.fixture
async def reversing(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Gateway]:
    """The same module, its read answered by an upstream that repeats the key reversed."""
    async for gateway in _gateway(engine, seed, tenant, catalog_tools, "/echo-key-reversed"):
        yield gateway


async def _run(g: Gateway, base: str, target: str, args: dict[str, Any], **extra: Any) -> dict[str, Any]:
    body = {"operation": g.tool(base), "contextId": "owner", "target": target, "input": args, **extra}
    r = await g.client.post(f"{BASE}/test", json=body)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _op(g: Gateway, base: str) -> dict[str, Any]:
    detail = (await g.client.get(BASE)).json()["data"]
    return next(o for o in detail["operations"] if o["name"] == g.tool(base))


async def test_a_draft_mock_and_transform_run_without_changing_the_operation(g: Gateway) -> None:
    draft = {"stub": {"balance": 1520.33, "lines": [1, 2]}, "responseTransform": '{"b": {{ data.balance }}}'}
    out = await _run(g, "place_hold", "stub", {"accountId": "CHQ-1", "hours": 1}, draft=draft)
    assert (out["output"], out["rawResponse"]) == ({"b": 1520.33}, draft["stub"]), out
    messages = [line["message"] for line in out["log"]]
    assert messages[-2:] == ["Answered from the mock response", "Draft transform applied"], messages
    op = await _op(g, "place_hold")
    assert op["stub"] == {"ok": True} and "responseTransform" not in op, "a test staged its draft"
    assert (await g.client.get(BASE)).json()["data"]["pendingChanges"] == []


async def test_a_failing_transform_returns_the_raw_answer_with_the_reason(g: Gateway) -> None:
    draft = {"stub": {"balance": 5}, "responseTransform": '{"b": {{ data.closing.balance }}}'}
    out = await _run(g, "place_hold", "stub", {"accountId": "CHQ-1", "hours": 1}, draft=draft)
    assert out["transformError"] and "closing" in out["transformError"], out
    assert out["output"] == out["rawResponse"] == {"balance": 5}


async def test_a_typed_secret_is_used_once_masked_in_the_request_and_stored_nowhere(
    g: Gateway, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    out = await _run(g, "get_account", "sandbox", {"accountId": "CHQ-2219"}, secretValues={"WB_BANK_KEY": TYPED})
    sent = g.received[-1]
    assert sent["headers"]["x-api-key"] == TYPED and TYPED in sent["query"], "the typed value was not the one sent"
    request = out["request"]
    assert request["url"].endswith("api_key=%5Bsecret%5D") or "[secret]" in request["url"], request
    assert {h["key"]: h["value"] for h in request["headers"]}["X-Api-Key"] == "[secret]", request
    assert any(line["message"] == "Secret WB_BANK_KEY from the value typed for this run" for line in out["log"])
    assert TYPED not in json.dumps(out), "the response carries the value"
    assert TYPED not in caplog.text, "a log line carries the value"
    async with engine.connect() as c:
        tables = (
            await c.execute(sa.text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
        ).scalars()
        found = [
            t
            for t in list(tables)
            if (
                await c.execute(sa.text(f'SELECT count(*) FROM "{t}" r WHERE r::text LIKE :v'), {"v": f"%{TYPED}%"})
            ).scalar_one()
        ]
    assert found == [], f"the typed value is stored in {found}"


async def test_an_edited_mock_is_a_staged_change_the_review_lists(g: Gateway) -> None:
    op = await _op(g, "place_hold")
    staged = await g.client.patch(f"{BASE}/operations/{op['id']}", json={"stub": {"holdId": "H-1"}})
    assert staged.status_code == 200, staged.text
    changes = staged.json()["data"]["pendingChanges"]
    edited = {"operation": g.tool("place_hold"), "kind": "settings", "detail": "Mock response edited", "major": False}
    assert edited in [{k: c[k] for k in ("operation", "kind", "detail", "major")} for c in changes], changes
    out = await _run(g, "place_hold", "stub", {"accountId": "CHQ-1", "hours": 1})
    assert out["output"] == {"holdId": "H-1"}, "a test without a draft answers from the staged mock"


async def test_a_draft_mock_over_the_size_limit_is_refused(g: Gateway) -> None:
    body = {
        "operation": g.tool("place_hold"),
        "contextId": "owner",
        "target": "stub",
        "input": {"accountId": "C", "hours": 1},
    }
    r = await g.client.post(f"{BASE}/test", json={**body, "draft": {"stub": {"blob": "x" * 70_000}}})
    assert r.status_code == 400 and "under 64 KB" in r.text, r.text


async def test_a_draft_transform_cannot_turn_a_secret_back_into_the_answer(reversing: Gateway) -> None:
    draft = {"responseTransform": '{"k": "{{ data.k[::-1] }}"}'}
    out = await _run(
        reversing, "get_account", "sandbox", {"accountId": "C"}, secretValues={"WB_BANK_KEY": TYPED}, draft=draft
    )
    assert reversing.received[-1]["headers"]["x-api-key"] == TYPED, "the typed value was not the one sent"
    assert out["output"] == {"k": "[secret]"}, out["output"]


async def test_a_cleared_transform_runs_with_none_of_the_operations_own(g: Gateway) -> None:
    op = await _op(g, "place_hold")
    staged = await g.client.patch(f"{BASE}/operations/{op['id']}", json={"responseTransform": '{"wrapped": true}'})
    assert staged.status_code == 200, staged.text
    out = await _run(g, "place_hold", "stub", {"accountId": "C", "hours": 1}, draft={"responseTransform": None})
    assert out["output"] == out["rawResponse"] == {"ok": True}, out
    assert "Transform applied" not in [line["message"] for line in out["log"]]
