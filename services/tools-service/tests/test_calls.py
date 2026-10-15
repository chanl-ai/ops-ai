"""/v1/calls on the database registry, one test per way a tool call could run when it should not, or run without a
record. HTTP operations call an in-process fake bank that records what it receives, so "nothing left the gateway"
is checked on the upstream's side. Needs OPA from the compose stack (`make db-up`)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.contract import response_checker
from ops_service_kit.ids import input_hash, new_id
from ops_tools.modules.seed import blank, load
from ops_tools.store.egress import EgressStore
from ops_tools.store.modules import ModuleStore
from ops_tools.tokens import Binding, mint

from .conftest import OPA_URL, REVIEW_KEY, build_app, service_headers
from .fake_upstream import ENDPOINT, HOST, SlowAware, fake_bank

MODULE = "mod_bank_api"


def _op(
    n: int, name: str, access: str, *, method: str, path: str, fields: list[dict[str, Any]], **extra: Any
) -> dict[str, Any]:
    return {
        "id": f"{MODULE}_op{n}",
        "tool_id": f"tl_{name}",
        "name": name,
        "description": name,
        "access": access,
        "enabled": True,
        "executor": "http",
        "method": method,
        "path": path,
        "headers": [],
        "body": None,
        "input": fields,
        "masked_output": [],
        "binding": None,
        "rate_limit_per_min": 60,
        "requires_approval": access != "read",
        "amount_max": None,
        "stub": {"ok": True},
        **extra,
    }


def bank_module(tenant: str, suffix: str) -> dict[str, Any]:
    """A published module calling the fake bank. Operation names carry `suffix`, unique within the tenant."""
    m = blank(
        module_id=MODULE,
        tenant_id=tenant,
        team_id="team_platform",
        owner="Platform",
        me="James Richardson",
        at=datetime.now(UTC),
        input={"displayName": "Bank API", "name": "bank-api", "type": "http"},
    )
    account = {"name": "accountId", "type": "string", "required": True}
    hold = [account, {"name": "hours", "type": "integer", "required": True}]
    m.update(
        status="published",
        endpoint=ENDPOINT,
        egress_hosts=[HOST],
        version="1.0.0",
        operations=[
            _op(
                1,
                f"get_account_{suffix}",
                "read",
                method="GET",
                path="/accounts/{accountId}",
                fields=[account],
                masked_output=["holder.sin"],
            ),
            _op(2, f"place_hold_{suffix}", "write", method="POST", path="/holds", fields=hold),
            _op(3, f"limited_{suffix}", "read", method="GET", path="/limited", fields=[]),
            _op(4, f"broken_{suffix}", "read", method="GET", path="/broken", fields=[]),
            _op(5, f"elsewhere_{suffix}", "read", method="GET", path="/accounts/{accountId}", fields=[account]),
        ],
    )
    return m


@dataclass
class Gateway:
    client: httpx.AsyncClient
    received: list[dict[str, Any]]
    suffix: str
    thread: str
    tenant: str

    def tool(self, base: str) -> str:
        return f"{base}_{self.suffix}"

    async def call(self, base: str, args: dict[str, Any], *, step: str, token: str | None = None) -> httpx.Response:
        body = {
            "tool": self.tool(base),
            "input": args,
            "key": step,
            "runContext": {"thread": self.thread, "step": step, "act": "agent:dispute_triage"},
            "approvalToken": token,
        }
        return await self.client.post("/v1/calls", json=body, headers=service_headers(self.tenant))

    def token(self, base: str, args: dict[str, Any], *, step: str) -> str:
        binding = Binding(self.thread, step, self.tool(base), input_hash(args), ["Maya Okafor"])
        return mint(binding, REVIEW_KEY, ttl_s=300)


@pytest.fixture
async def gateway(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Gateway]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    suffix = new_id("x")[2:8].lower()
    module = bank_module(tenant, suffix)
    await EgressStore(engine).add(tenant, "host", HOST, actor="test", note="", at=datetime.now(UTC))
    await ModuleStore(engine).put(module, expected_revision=None)
    bank, received = fake_bank()
    async with (
        httpx.AsyncClient(base_url=OPA_URL) as opa,
        httpx.AsyncClient(transport=SlowAware(httpx.ASGITransport(app=bank))) as upstream,
    ):
        app = build_app(engine, seed, tenant, opa=opa, upstream=upstream)
        hooks = {"response": [response_checker(app)]}
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks) as c,
        ):
            yield Gateway(c, received, suffix, new_id("gth"), tenant)


async def _executions(g: Gateway, **params: str) -> list[dict[str, Any]]:
    r = await g.client.get("/v1/executions", params={"tool": g.tool(params.pop("base")), **params})
    assert r.status_code == 200, r.text
    return r.json()["data"]["data"]


async def test_a_read_runs_against_the_upstream_masked_and_logged_with_its_caller(gateway: Gateway) -> None:
    r = await gateway.call("get_account", {"accountId": "CHQ-2219"}, step="s1")
    assert r.status_code == 200, r.text
    out = r.json()["data"]["output"]
    assert out["accountId"] == "CHQ-2219" and out["holder"]["sin"] == "[redacted]"
    assert [x["path"] for x in gateway.received] == ["/v1/accounts/CHQ-2219"]
    [row] = await _executions(gateway, base="get_account")
    # The caller is the verified service token's subject, not anything the body says.
    assert row["subject"] == {"kind": "service", "id": "service:agents", "name": "service:agents"}
    assert row["actor"]["kind"] == "agent" and row["runId"] == gateway.thread and row["step"] == "s1"
    assert (row["decision"], row["status"], row["system"]) == ("allow", "ok", "Bank API")


async def test_a_tool_the_registry_does_not_know_is_refused(gateway: Gateway) -> None:
    body: dict[str, Any] = {"tool": "drop_tables", "input": {}, "key": "s1", "runContext": {}}
    r = await gateway.client.post("/v1/calls", json=body, headers=service_headers(gateway.tenant))
    assert r.status_code == 403
    assert not gateway.received


async def test_a_hidden_operation_is_refused(gateway: Gateway, engine: AsyncEngine, tenant: str) -> None:
    store = ModuleStore(engine)
    m = await store.get(tenant, MODULE)
    assert m is not None
    m["operations"][0]["enabled"] = False
    await store.put(m, expected_revision=m["revision"])
    r = await gateway.call("get_account", {"accountId": "CHQ-2219"}, step="s1")
    assert r.status_code == 403 and r.json()["error"]["code"] == "operation_hidden"
    assert not gateway.received


async def test_input_failing_the_schema_never_reaches_the_upstream(gateway: Gateway) -> None:
    r = await gateway.call("place_hold", {"accountId": "CHQ-2219", "hours": "a day"}, step="s1")
    assert r.status_code == 422
    assert r.json()["error"]["details"]["invalid"] == [{"field": "hours", "message": "Expected integer."}]
    r = await gateway.call("get_account", {"accountId": "CHQ-2219", "customerId": "CUS-1"}, step="s2")
    assert r.status_code == 422, "an argument the operation does not declare is refused"
    assert not gateway.received
    [row, _] = await _executions(gateway, base="place_hold") + await _executions(gateway, base="get_account")
    assert (row["decision"], row["status"]) == ("deny", "denied")


async def test_a_write_without_an_approval_token_is_refused_and_with_one_it_runs(gateway: Gateway) -> None:
    args = {"accountId": "CHQ-2219", "hours": 24}
    refused = await gateway.call("place_hold", args, step="s1")
    assert refused.status_code == 403
    assert not gateway.received, "the registry's write class made OPA demand a token"
    ran = await gateway.call("place_hold", args, step="s1", token=gateway.token("place_hold", args, step="s1"))
    assert ran.status_code == 200, ran.text
    assert ran.json()["data"]["output"]["request"] == args
    rows = await _executions(gateway, base="place_hold")
    assert rows[0]["approvalTokenId"].startswith("apt:") and rows[0]["approval"]["kind"] == "person"


async def test_upstream_failures_are_logged_as_errors(gateway: Gateway) -> None:
    limited = await gateway.call("limited", {}, step="s1")
    broken = await gateway.call("broken", {}, step="s2")
    assert limited.json()["data"]["ok"] is False and broken.json()["data"]["ok"] is False
    assert limited.json()["data"]["output"]["error"]["code"] == "RATE_LIMITED"
    assert broken.json()["data"]["output"]["error"]["code"] == "UPSTREAM_ERROR"
    for base in ("limited", "broken"):
        [row] = await _executions(gateway, base=base)
        assert row["status"] == "error"


async def test_egress_goes_only_to_the_modules_hosts(gateway: Gateway, engine: AsyncEngine, tenant: str) -> None:
    store = ModuleStore(engine)
    m = await store.get(tenant, MODULE)
    assert m is not None
    m["endpoint"] = "https://exfil.example.com/v1"
    await store.put(m, expected_revision=m["revision"])
    r = await gateway.call("elsewhere", {"accountId": "CHQ-2219"}, step="s1")
    assert r.json()["data"]["output"]["error"]["code"] == "EGRESS_DENIED"
    assert not gateway.received


async def test_one_key_with_another_body_is_not_answered_with_the_first_result(gateway: Gateway) -> None:
    first, second = {"accountId": "CHQ-1", "hours": 24}, {"accountId": "CHQ-2", "hours": 48}
    a = await gateway.call("place_hold", first, step="s1", token=gateway.token("place_hold", first, step="s1"))
    b = await gateway.call("place_hold", second, step="s1", token=gateway.token("place_hold", second, step="s1"))
    assert a.json()["data"]["output"]["request"] == first
    assert b.json()["data"]["output"]["request"] == second
    assert "replayOf" not in b.json()["data"]


async def test_the_registry_and_the_agents_catalogue_agree_on_every_access_class(
    gateway: Gateway, engine: AsyncEngine, tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    store = ModuleStore(engine)
    for t in [*catalog_tools, {"name": "send_reply", "access": "write"}]:
        found = await store.operation_named(tenant, t["name"])
        assert found is not None, f"{t['name']} is in the registry"
        assert (found[1]["access"], found[1]["executor"]) == (t["access"], "local"), t["name"]


async def test_an_approved_write_runs_after_opa_reloads_its_data_and_loses_the_review_key(gateway: Gateway) -> None:
    """OPA's file watch reloads data.ops from the mounted policy folder, dropping the key the gateway wrote at start
    (c-048 G23: every approved write on the shared stack read as unsigned)."""
    async with httpx.AsyncClient(base_url=OPA_URL) as opa:
        (await opa.put("/v1/data/ops", json={"identities": ["service:agents"]})).raise_for_status()
    args = {"accountId": "CHQ-2219", "hours": 24}
    ran = await gateway.call("place_hold", args, step="s1", token=gateway.token("place_hold", args, step="s1"))
    assert ran.status_code == 200, ran.text
    forged = mint(
        Binding(gateway.thread, "s2", gateway.tool("place_hold"), input_hash(args), ["Maya Okafor"]),
        "x" * 32,
        ttl_s=300,
    )
    refused = await gateway.call("place_hold", args, step="s2", token=forged)
    assert refused.status_code == 403
    assert "approval token is not signed by the review service" in refused.json()["error"]["details"]["reasons"]


async def test_a_write_whose_policy_needs_two_approvers_refuses_a_token_naming_one(
    gateway: Gateway, engine: AsyncEngine, tenant: str
) -> None:
    store = ModuleStore(engine)
    m = await store.get(tenant, MODULE)
    assert m is not None
    for o in m["operations"]:
        if o["name"] == gateway.tool("place_hold"):
            o["approvers"] = 2
    await store.put(m, expected_revision=m["revision"])
    args = {"accountId": "CHQ-2219", "hours": 24}
    one = await gateway.call("place_hold", args, step="s1", token=gateway.token("place_hold", args, step="s1"))
    assert one.status_code == 403
    assert "this write needs 2 approvers; the token has 1" in one.json()["error"]["details"]["reasons"]
    assert not gateway.received
    pair = Binding(gateway.thread, "s2", gateway.tool("place_hold"), input_hash(args), ["Maya Okafor", "Dana Reyes"])
    two = await gateway.call("place_hold", args, step="s2", token=mint(pair, REVIEW_KEY, ttl_s=300))
    assert two.status_code == 200, two.text
