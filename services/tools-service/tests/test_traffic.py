"""A module's traffic comes from gateway_calls (c-041): the window, what counts as a call, and the module's own p95."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import new_id
from ops_tools.store.calls import CallLog

from .conftest import Api

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def logged(
    log: CallLog,
    module_id: str | None,
    tool: str,
    *,
    outcome: str,
    latency: int,
    at: datetime,
    tenant: str = "local",
    thread: str | None = None,
) -> str:
    row: dict[str, Any] = {
        "tenant_id": tenant,
        "thread_id": thread,
        "id": new_id("call"),
        "tool": tool,
        "access": "read",
        "input_hash": new_id("h"),
        "idempotency_key": new_id("k"),
        "sub": "agent:test",
        "decision": "deny" if outcome == "refused" else "allow",
        "reasons": [],
        "approvers": [],
        "outcome": outcome,
        "created_at": iso(at),
        "module_id": module_id,
        "latency_ms": latency,
    }
    await log.record(**row)
    return str(row["id"])


async def test_traffic_counts_calls_that_ran_in_the_window(engine: AsyncEngine) -> None:
    log = CallLog(engine)
    mod, other = new_id("mod"), new_id("mod")
    for ms in (10, 20, 30, 40):
        await logged(log, mod, "fast", outcome="ok", latency=ms, at=NOW - timedelta(hours=1))
    await logged(log, mod, "slow", outcome="error", latency=900, at=NOW - timedelta(hours=2))
    await logged(log, mod, "fast", outcome="refused", latency=1, at=NOW - timedelta(hours=1))
    await logged(log, mod, "fast", outcome="replayed", latency=1, at=NOW - timedelta(hours=1))
    await logged(log, mod, "fast", outcome="ok", latency=5000, at=NOW - timedelta(hours=25))
    await logged(log, other, "fast", outcome="ok", latency=10, at=NOW - timedelta(hours=1))

    t = await log.traffic([mod], iso(NOW - timedelta(days=1)), tenant_id="local")

    assert t[(mod, "fast")] == {"calls": 4, "errors": 0, "p95Ms": 38}
    assert t[(mod, "slow")] == {"calls": 1, "errors": 1, "p95Ms": 900}
    # The module's p95 is over all five calls, not the larger of its operations' p95s.
    assert t[(mod, None)]["calls"] == 5 and t[(mod, None)]["errors"] == 1
    assert 38 < t[(mod, None)]["p95Ms"] < 900
    assert all(k[0] == mod for k in t)


async def test_daily_groups_by_utc_day(engine: AsyncEngine) -> None:
    log = CallLog(engine)
    mod = new_id("mod")
    await logged(log, mod, "op", outcome="ok", latency=10, at=NOW)
    await logged(log, mod, "op", outcome="error", latency=10, at=NOW - timedelta(hours=1))
    await logged(log, mod, "op", outcome="ok", latency=10, at=NOW - timedelta(days=3))
    await logged(log, mod, "op", outcome="ok", latency=10, at=NOW - timedelta(days=20))

    days = await log.daily(mod, (NOW - timedelta(days=13)).date().isoformat(), tenant_id="local")

    assert days == {
        "2026-10-12": {"count": 2, "errors": 1, "p95Ms": 10},
        "2026-10-09": {"count": 1, "errors": 0, "p95Ms": 10},
    }


async def test_an_activity_row_opens_to_its_call(bank_api: Api, gateway_call: Any) -> None:
    """c-057 T013: GET /v1/executions/{id} answers the row the list shows, so an Activity row opens to its call, and
    404 for an id that is not one. A call refused for a missing secret is still a logged call."""
    from .fake_upstream import ENDPOINT, HOST  # noqa: PLC0415 - the fake bank's names, as test_import reads them

    await bank_api.client.post("/v1/egress/hosts", json={"value": HOST})
    op: dict[str, Any] = {"name": "get_account", "description": "", "access": "read", "group": "accounts", "input": []}
    source = {"kind": "openapi", "specUrl": f"{ENDPOINT}/openapi.json"}
    r = await bank_api.call(
        "POST", "/mod_document_service/operations/import", json={"source": source, "operations": [op]}
    )
    assert r.status_code == 200, r.text
    called = await gateway_call("get_account", {"accountId": "CHQ-1"})
    assert called.status_code == 200, called.text
    listed = (await bank_api.client.get("/v1/executions", params={"tool": "get_account"})).json()["data"]["data"]
    assert listed, "the call was logged"
    one = await bank_api.client.get(f"/v1/executions/{listed[0]['id']}")
    assert one.status_code == 200, one.text
    assert one.json()["data"] == listed[0]
    missing = await bank_api.client.get("/v1/executions/gwc_nobody")
    assert missing.status_code == 404


# ── Tenant isolation (c-057 T013, security review): one test per read that another tenant's call is not visible ──


async def test_the_executions_list_shows_only_the_callers_tenant(api: Api, engine: AsyncEngine) -> None:
    """A scope-all team saw every tenant's calls: the list filtered by module only, and a call on no module belonged
    to nobody."""
    log = CallLog(engine)
    mine = await logged(log, None, "shared_tool", outcome="ok", latency=1, at=NOW, tenant=api.tenant)
    theirs = await logged(log, None, "shared_tool", outcome="ok", latency=1, at=NOW, tenant="tenant_other")
    r = await api.client.get("/v1/executions", params={"tool": "shared_tool", "pageSize": 200})
    assert r.status_code == 200, r.text
    ids = {row["id"] for row in r.json()["data"]["data"]}
    assert mine in ids and theirs not in ids, ids


async def test_one_call_is_not_served_to_another_tenant(api: Api, engine: AsyncEngine) -> None:
    log = CallLog(engine)
    theirs = await logged(log, None, "shared_tool", outcome="ok", latency=1, at=NOW, tenant="tenant_other")
    assert (await api.client.get(f"/v1/executions/{theirs}")).status_code == 404
    mine = await logged(log, None, "shared_tool", outcome="ok", latency=1, at=NOW, tenant=api.tenant)
    assert (await api.client.get(f"/v1/executions/{mine}")).status_code == 200


async def test_traffic_counts_only_the_tenants_calls_even_on_the_same_module_id(engine: AsyncEngine) -> None:
    log = CallLog(engine)
    mod = new_id("mod")
    await logged(log, mod, "op", outcome="ok", latency=10, at=NOW, tenant="tenant_a")
    await logged(log, mod, "op", outcome="error", latency=900, at=NOW, tenant="tenant_b")
    t = await log.traffic([mod], iso(NOW - timedelta(days=1)), tenant_id="tenant_a")
    assert t[(mod, "op")] == {"calls": 1, "errors": 0, "p95Ms": 10}


async def test_the_activity_days_count_only_the_tenants_calls(engine: AsyncEngine) -> None:
    log = CallLog(engine)
    mod = new_id("mod")
    await logged(log, mod, "op", outcome="ok", latency=10, at=NOW, tenant="tenant_a")
    await logged(log, mod, "op", outcome="ok", latency=10, at=NOW, tenant="tenant_b")
    days = await log.daily(mod, (NOW - timedelta(days=1)).date().isoformat(), tenant_id="tenant_a")
    assert days == {"2026-10-12": {"count": 1, "errors": 0, "p95Ms": 10}}


async def test_the_thread_filter_shows_only_the_tenants_calls_on_that_thread(engine: AsyncEngine) -> None:
    log = CallLog(engine)
    thread = new_id("gth")
    mine = await logged(log, None, "op", outcome="ok", latency=1, at=NOW, tenant="tenant_a", thread=thread)
    await logged(log, None, "op", outcome="ok", latency=1, at=NOW, tenant="tenant_b", thread=thread)
    rows, total = await log.search(thread_id=thread, tenant_id="tenant_a")
    assert total == 1 and [r["id"] for r in rows] == [mine]
    assert [r["id"] for r in await log.for_thread(thread, tenant_id="tenant_a")] == [mine]


async def test_a_call_with_no_tenant_is_read_by_nobody(engine: AsyncEngine) -> None:
    """A row older than the tenant column, on no known module: excluded from every read rather than shown to all."""
    log = CallLog(engine)
    thread = new_id("gth")
    await logged(log, None, "op", outcome="ok", latency=1, at=NOW, tenant=None, thread=thread)  # type: ignore[arg-type]
    rows, total = await log.search(thread_id=thread, tenant_id="local")
    assert (rows, total) == ([], 0)
