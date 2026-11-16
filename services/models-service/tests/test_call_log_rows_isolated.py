"""Each tenant's model calls are held to that tenant by the database, by failure mode: a tenant's read shows another
tenant's calls, even with SQL that names no tenant, which only the policy can stop; the install scope reads the log
past every tenant; a call that names no tenant lands in the policed log with no tenant. Runs on the test database as
`ops_models_tenant`."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa

from ops_models.store import CallLog
from ops_models.store.tables import model_call_log, model_call_refusals
from ops_store import isolation
from ops_store.schema import isolation_kind
from ops_store.team_scope import InstallScopeError

from .conftest import Models

ROLE = "ops_models_tenant"


def _row(key_id: str, tenant: str | None) -> dict[str, object]:
    return {
        "id": f"mc_{uuid4().hex[:12]}",
        "key_id": key_id,
        "alias": "bank-standard",
        "input_tokens": 1,
        "output_tokens": 1,
        "cost": Decimal("0.01"),
        "latency_ms": 1,
        "outcome": "ok",
        "tenant_id": tenant,
    }


async def test_a_tenant_reads_only_its_own_calls_and_the_install_scope_reads_none(models: Models) -> None:
    assert isolation_kind(model_call_log) == "tenant"
    key_id = f"workflow:iso-{uuid4().hex[:8]}"
    mine, other = f"t_{uuid4().hex[:8]}", f"t_{uuid4().hex[:8]}"
    log = CallLog(models.engine)
    for tenant in (mine, other):
        with isolation.scope(tenant, None):
            await log.record(_row(key_id, tenant))
    with isolation.scope(mine, None):
        rows, totals = await log.page(key_id=key_id)
        async with isolation.isolated_tx(models.engine, role=ROLE) as c:
            q = sa.text("SELECT count(*) FROM model_call_log WHERE key_id = :k")
            seen = (await c.execute(q, {"k": key_id})).scalar_one()
    assert (len(rows), [t.calls for t in totals], seen) == (1, [1], 1), "a tenant read another tenant's call"
    with pytest.raises(InstallScopeError):
        async with log.install_tx("probe") as c:
            await c.execute(sa.select(sa.func.count()).select_from(model_call_log))
    # Both calls count toward the key's caps, whichever tenant made them.
    assert (await log.totals(key_id, datetime.now(UTC))).today == Decimal("0.02")


async def test_a_call_that_names_no_tenant_is_kept_apart_from_every_tenants_log(models: Models) -> None:
    key_id = f"workflow:none-{uuid4().hex[:8]}"
    log, row = CallLog(models.engine), _row(key_id, None)
    await log.record(row)
    async with log.spend.install_tx("probe") as c:
        q = sa.select(sa.func.count()).select_from(model_call_refusals).where(model_call_refusals.c.id == row["id"])
        kept = (await c.execute(q)).scalar_one()
    async with models.engine.connect() as c:
        # The database's owner, past the policy: the log has no tenant-less row for the key.
        await c.execute(sa.text("SET LOCAL row_security = off"))
        q = sa.select(sa.func.count()).select_from(model_call_log).where(model_call_log.c.key_id == key_id)
        logged = (await c.execute(q)).scalar_one()
    assert (kept, logged) == (1, 0)
    assert (await log.totals(key_id, datetime.now(UTC))).recent == 1, "the refusal still counts toward the rate"
