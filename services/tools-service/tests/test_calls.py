"""/v1/calls on the database registry, one test per way a tool call could run when it should not, or run without a
record. HTTP operations call an in-process fake bank that records what it receives, so "nothing left the gateway"
is checked on the upstream's side. Needs OPA from the compose stack (`make db-up`)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.contract import response_checker
from ops_service_kit.ids import input_hash, new_id
from ops_tools.modules.seed import blank, load
from ops_tools.store import CallLog
from ops_tools.store.egress import EgressStore
from ops_tools.store.modules import ModuleStore
from ops_tools.tokens import Binding, mint

from .conftest import REVIEW_KEY, build_app, opa_client, service_headers
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
    async with opa_client() as opa:
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


# ── Tenant isolation of the call log (c-057 T013, security review), on the real routes ──


@pytest.fixture
async def other_tenant(
    engine: AsyncEngine, seed: dict[str, Any], catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    """A second tenant's dev user on the same database, its registry seeded too, so it holds modules under the same
    ids as the first: what any other tenant of this gateway looks like."""
    tenant = f"t_{uuid4().hex[:10]}"
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    async with opa_client() as opa:
        other = build_app(engine, seed, tenant, opa=opa)
        async with (
            other.router.lifespan_context(other),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=other), base_url="http://tools") as c,
        ):
            yield c


async def test_probe_another_tenants_call_is_not_in_its_executions(
    gateway: Gateway, other_tenant: httpx.AsyncClient
) -> None:
    """Reviewer probe: a call made in one tenant must not appear in another tenant's executions list or detail."""
    r = await gateway.call("get_account", {"accountId": "CHQ-2219"}, step="s1")
    assert r.status_code == 200, r.text
    mine = await _executions(gateway, base="get_account")
    assert mine, "the call was not logged in its own tenant"
    call_id = mine[0]["id"]
    listed = (await other_tenant.get("/v1/executions", params={"pageSize": 200})).json()["data"]["data"]
    detail = await other_tenant.get(f"/v1/executions/{call_id}")
    leaked = [x["id"] for x in listed if x["id"] == call_id]
    assert not leaked and detail.status_code == 404, (leaked, detail.status_code, detail.text[:200])


async def test_another_tenants_call_is_not_in_a_modules_traffic_or_activity(
    gateway: Gateway, other_tenant: httpx.AsyncClient
) -> None:
    """The same shape for the module list's call counts (traffic) and the module page's activity tab: both tenants
    hold the seeded mod_core_banking; a call on it in one tenant counts for nothing in the other."""
    body = {
        "tool": "get_customer_profile",
        "input": {"customerId": "CUS-118842"},
        "key": "s-profile",
        "runContext": {"thread": gateway.thread, "step": "s-profile", "act": "agent:dispute_triage"},
    }
    r = await gateway.client.post("/v1/calls", json=body, headers=service_headers(gateway.tenant))
    assert r.status_code == 200 and r.json()["data"]["ok"], r.text
    mine = (await gateway.client.get("/v1/tool-modules/mod_core_banking")).json()["data"]
    assert mine["calls24h"] == 1, "non-vacuous: the call counts in its own tenant"
    rows = (await other_tenant.get("/v1/tool-modules", params={"pageSize": 200})).json()["data"]["data"]
    same = next(m for m in rows if m["id"] == "mod_core_banking")
    assert same["calls24h"] == 0, same
    activity = (await other_tenant.get("/v1/tool-modules/mod_core_banking/activity")).json()["data"]
    assert sum(d["count"] for d in activity["days"]) == 0 and activity["recent"] == [], activity


async def test_executions_find_the_call_sent_under_one_key(gateway: Gateway) -> None:
    """A workflow run reconciles a write after a crash by its key (c-061 T005): the filter finds that call alone, and
    a key never sent finds nothing, which the run reads as "the write never arrived"."""
    for step in ("wfrun_a:lookup:1:1", "wfrun_a:lookup:1:2"):
        r = await gateway.call("get_account", {"accountId": "CHQ-2219"}, step=step)
        assert r.status_code == 200, r.text
    found = await _executions(gateway, base="get_account", key="wfrun_a:lookup:1:1")
    assert [(c["step"], c["outcome"]) for c in found] == [("wfrun_a:lookup:1:1", "ok")]
    assert await _executions(gateway, base="get_account", key="wfrun_a:lookup:1:9") == []


async def test_a_write_received_but_not_finished_reads_as_running_by_its_key(
    gateway: Gateway, engine: AsyncEngine
) -> None:
    """The gateway claims a write's row (outcome running) when it receives the call, before the executor runs. A
    workflow reconciling by key must see that as not yet known, never as done; Executions shows it running (c-561)."""
    key = f"wfrun_{uuid4().hex[:8]}:hold:1:1"
    row: dict[str, Any] = {
        "id": new_id("call"),
        "tenant_id": gateway.tenant,
        "tool": gateway.tool("place_hold"),
        "access": "write",
        "input_hash": "h",
        "idempotency_key": key,
        "thread_id": key.split(":", maxsplit=1)[0],
        "step": key,
        "sub": "service:agents",
        "act": "graph",
        "approvers": [],
        "created_at": datetime.now(UTC).isoformat(),
        "module_id": MODULE,
        "approval_token_id": None,
        "decision": "allow",
        "reasons": [],
    }
    assert await CallLog(engine).claim(generation=None, **row) is None
    (found,) = await _executions(gateway, base="place_hold", key=key)
    assert (found["outcome"], found["status"]) == ("running", "running")


async def _abandon(gateway: Gateway, key: str) -> httpx.Response:
    body = {"key": key, "tool": gateway.tool("place_hold"), "thread": gateway.thread}
    return await gateway.client.post("/v1/calls/abandon", json=body, headers=service_headers(gateway.tenant))


async def test_a_write_abandoned_by_its_caller_is_refused_when_it_arrives_late(gateway: Gateway) -> None:
    """A workflow that lost the answer to a write and found no record of it abandons the key before it takes the
    error port; the same call reaching the gateway afterwards (it was still in flight) runs nothing."""
    args = {"accountId": "CHQ-2219", "hours": 24}
    key = f"{gateway.thread}:hold:1:1"
    abandoned = await _abandon(gateway, key)
    assert abandoned.status_code == 200 and abandoned.json()["data"] == {"abandoned": True, "call": None}
    late = await gateway.call("place_hold", args, step=key, token=gateway.token("place_hold", args, step=key))
    assert late.status_code == 409 and late.json()["error"]["code"] == "call_abandoned", late.text
    assert not gateway.received, "an abandoned write never reaches the system"


async def test_abandoning_a_write_the_gateway_already_has_returns_that_call(gateway: Gateway) -> None:
    args = {"accountId": "CHQ-2219", "hours": 24}
    key = f"{gateway.thread}:hold:2:1"
    ran = await gateway.call("place_hold", args, step=key, token=gateway.token("place_hold", args, step=key))
    assert ran.status_code == 200, ran.text
    found = (await _abandon(gateway, key)).json()["data"]
    assert found["abandoned"] is False and found["call"]["outcome"] == "ok" and found["call"]["effect"] is True


async def test_a_write_running_past_its_expiry_reads_as_lost(gateway: Gateway, engine: AsyncEngine) -> None:
    """A gateway that died mid-execute leaves its claim running; past the expiry the row reads as lost (whether the
    system acted is unknown), never as still running forever."""
    key = f"wfrun_{uuid4().hex[:8]}:hold:1:1"
    row: dict[str, Any] = {
        "id": new_id("call"),
        "tenant_id": gateway.tenant,
        "tool": gateway.tool("place_hold"),
        "access": "write",
        "input_hash": "h2",
        "idempotency_key": key,
        "thread_id": key.split(":", maxsplit=1)[0],
        "step": key,
        "sub": "service:agents",
        "act": "graph",
        "approvers": [],
        "created_at": "2026-01-01T00:00:00.000Z",
        "module_id": MODULE,
        "approval_token_id": None,
        "decision": "allow",
        "reasons": [],
    }
    assert await CallLog(engine).claim(generation=None, **row) is None
    (found,) = await _executions(gateway, base="place_hold", key=key)
    assert (found["outcome"], found["effect"]) == ("lost", True)


async def test_an_approved_write_with_no_thread_runs_once_by_its_key(gateway: Gateway) -> None:
    """A caller outside a graph run has no thread; the same approved write sent twice must still act once."""
    args = {"accountId": "CHQ-2219", "hours": 24}
    tool = gateway.tool("place_hold")
    token = mint(Binding(None, "k1", tool, input_hash(args), ["Maya Okafor"]), REVIEW_KEY, ttl_s=300)  # type: ignore[arg-type]
    body = {
        "tool": tool,
        "input": args,
        "key": "k1",
        "runContext": {"step": "k1", "act": "agent:x"},
        "approvalToken": token,
    }
    first = await gateway.client.post("/v1/calls", json=body, headers=service_headers(gateway.tenant))
    again = await gateway.client.post("/v1/calls", json=body, headers=service_headers(gateway.tenant))
    assert first.status_code == 200 and again.status_code == 200, (first.text, again.text)
    assert again.json()["data"].get("replayOf") == first.json()["data"]["callId"]
    assert len([r for r in gateway.received if r["path"] == "/v1/holds"]) == 1, "the bank was asked to hold twice"


async def test_an_optional_field_left_out_is_sent_with_its_default(
    gateway: Gateway, engine: AsyncEngine, tenant: str
) -> None:
    """The agent's schema promises the default (c-073), so the system must receive it when the call omits the field."""
    store = ModuleStore(engine)
    m = await store.get(tenant, MODULE)
    assert m is not None
    for o in m["operations"]:
        if o["name"] == gateway.tool("get_account"):
            o["input"] = [*o["input"], {"name": "currency", "type": "string", "required": False, "default": "CAD"}]
    await store.put(m, expected_revision=m["revision"])
    left_out = await gateway.call("get_account", {"accountId": "CHQ-2219"}, step="d1")
    assert left_out.status_code == 200, left_out.text
    assert gateway.received[-1]["query"] == "currency=CAD"
    chosen = await gateway.call("get_account", {"accountId": "CHQ-2219", "currency": "USD"}, step="d2")
    assert chosen.status_code == 200 and gateway.received[-1]["query"] == "currency=USD"


async def test_an_approved_write_runs_only_the_input_its_token_binds(
    gateway: Gateway, engine: AsyncEngine, tenant: str
) -> None:
    """A default is never added to a write: the approval token binds the hash of what the approver saw."""
    store = ModuleStore(engine)
    m = await store.get(tenant, MODULE)
    assert m is not None
    for o in m["operations"]:
        if o["name"] == gateway.tool("place_hold"):
            o["input"] = [*o["input"], {"name": "note", "type": "string", "required": False, "default": "auto"}]
    await store.put(m, expected_revision=m["revision"])
    args = {"accountId": "CHQ-2219", "hours": 24}
    ran = await gateway.call("place_hold", args, step="w1", token=gateway.token("place_hold", args, step="w1"))
    assert ran.status_code == 200, ran.text
    assert ran.json()["data"]["output"]["request"] == args, "nothing beyond the approved input reached the system"


async def test_once_by_key_holds_by_a_plain_unique_index(gateway: Gateway, engine: AsyncEngine) -> None:
    """A partial index (WHERE effect) holds on PostgreSQL only; elsewhere it turns into a unique index on every row and
    threaded calls collide. The effect index is plain, and two threads making the same write each run once."""
    async with engine.connect() as c:
        defs = (
            (
                await c.execute(
                    sa.text(
                        "SELECT indexdef FROM pg_indexes WHERE tablename = 'gateway_calls' AND indexdef LIKE '%UNIQUE%'"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert defs and not [d for d in defs if " WHERE " in d], defs
    args = {"accountId": "CHQ-2219", "hours": 24}
    tool = gateway.tool("place_hold")
    for thread in ("gth_one", "gth_two"):
        token = mint(Binding(thread, "same", tool, input_hash(args), ["Maya Okafor"]), REVIEW_KEY, ttl_s=300)
        body = {
            "tool": tool,
            "input": args,
            "key": "same",
            "runContext": {"thread": thread, "step": "same"},
            "approvalToken": token,
        }
        r = await gateway.client.post("/v1/calls", json=body, headers=service_headers(gateway.tenant))
        assert r.status_code == 200 and "replayOf" not in r.json()["data"], r.text
    assert len([x for x in gateway.received if x["path"] == "/v1/holds"]) == 2
