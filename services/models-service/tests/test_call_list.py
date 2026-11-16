"""GET /v1/models/calls, by failure mode: a tenant sees another tenant's calls or misses its own; the rows come back
out of newest-first order; a row's fields or the per-key totals change in the list's move onto the shared list
contract; a filter stops filtering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from ops_identity import dev_service_signer, mint_service_token
from ops_models.store import CallLog
from ops_store import isolation

from .conftest import Models

START = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def _row(n: int, key_id: str, tenant: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"mc_{uuid4().hex[:12]}",
        "key_id": key_id,
        "alias": "bank-standard",
        "alias_version": 1,
        "provider_model": "scripted-standard",
        "input_tokens": 10 + n,
        "output_tokens": 20 + n,
        "cost": Decimal("0.0125") * (n + 1),
        "latency_ms": 5,
        "outcome": "ok",
        "tenant_id": tenant,
        "created_at": START + timedelta(minutes=n),
        **extra,
    }


async def _seed(models: Models, tenant: str, rows: list[dict[str, Any]]) -> None:
    log = CallLog(models.engine)
    with isolation.scope(tenant, None):
        for row in rows:
            await log.record(row)


async def _list(models: Models, tenant: str, **params: Any) -> dict[str, Any]:
    """The list as agents-service reads it, with a service token naming `tenant`."""
    token = mint_service_token(dev_service_signer(), service="agents", audience="models", tenant_id=tenant, ttl_s=3600)
    r = await models.client.get("/v1/models/calls", params=params, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_each_tenant_lists_only_its_calls_newest_first_with_its_key_totals(models: Models) -> None:
    run = uuid4().hex[:8]
    key_a, key_b = f"workflow:list-a-{run}", f"workflow:list-b-{run}"
    mine, other = f"t_mine_{run}", f"t_other_{run}"
    seeded = [_row(0, key_a, mine), _row(1, key_b, mine), _row(2, key_a, mine, alias="extract", outcome="denied")]
    theirs = [_row(3, key_a, other), _row(4, key_b, other)]
    await _seed(models, mine, seeded)
    await _seed(models, other, theirs)

    got = await _list(models, mine)
    assert [r["id"] for r in got["data"]] == [r["id"] for r in reversed(seeded)]
    assert got["data"][-1] == {
        "id": seeded[0]["id"],
        "keyId": key_a,
        "alias": "bank-standard",
        "aliasVersion": 1,
        "providerModel": "scripted-standard",
        "inputTokens": 10,
        "outputTokens": 20,
        "cost": "0.012500",
        "latencyMs": 5,
        "outcome": "ok",
        "reason": None,
        "runId": None,
        "stepId": None,
        "threadId": None,
        "requestHash": None,
        "createdAt": "2026-11-01T09:00:00+00:00",
        "images": 0,
    }
    totals = {t["keyId"]: (t["calls"], t["cost"]) for t in got["byKey"]}
    assert totals == {key_a: (2, "0.050000"), key_b: (1, "0.025000")}

    theirs_got = await _list(models, other)
    assert [r["id"] for r in theirs_got["data"]] == [theirs[1]["id"], theirs[0]["id"]]
    assert {t["keyId"]: t["calls"] for t in theirs_got["byKey"]} == {key_a: 1, key_b: 1}

    by_alias = await _list(models, mine, alias="extract")
    assert [r["id"] for r in by_alias["data"]] == [seeded[2]["id"]]
    assert {t["keyId"]: t["calls"] for t in by_alias["byKey"]} == {key_a: 1}
    by_key = await _list(models, mine, keyId=key_b)
    assert [r["id"] for r in by_key["data"]] == [seeded[1]["id"]]
    assert (await _list(models, mine, outcome="denied"))["byKey"] == [{"keyId": key_a, "calls": 1, "cost": "0.037500"}]


async def test_pages_hold_every_call_once_and_the_key_totals_count_every_page(models: Models) -> None:
    run = uuid4().hex[:8]
    key_a, key_b, tenant = f"workflow:page-a-{run}", f"workflow:page-b-{run}", f"t_page_{run}"
    # Three calls in one instant: only the id orders them, so without it a row repeats or vanishes between pages.
    same = {"created_at": START}
    seeded = [_row(0, key_a, tenant, **same), _row(1, key_b, tenant, **same), _row(2, key_a, tenant, **same)]
    seeded += [_row(3, key_b, tenant), _row(4, key_a, tenant)]
    await _seed(models, tenant, seeded)

    seen: list[str] = []
    for page in (1, 2, 3):
        got = await _list(models, tenant, page=page, pageSize=2)
        assert got["pagination"]["total"] == 5, got
        assert {t["keyId"]: t["calls"] for t in got["byKey"]} == {key_a: 3, key_b: 2}
        seen += [r["id"] for r in got["data"]]
    ties = sorted((r["id"] for r in seeded[:3]), reverse=True)
    assert seen == [seeded[4]["id"], seeded[3]["id"], *ties]

    picked = await _list(models, tenant, ids=[seeded[3]["id"]])
    assert [r["id"] for r in picked["data"]] == [seeded[3]["id"]]
    assert picked["byKey"] == [{"keyId": key_b, "calls": 1, "cost": "0.050000"}]
