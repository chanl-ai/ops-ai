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
from sqlalchemy import event

from ops_models.store import CallLog
from ops_models.store.tables import model_call_log, model_calls_untenanted
from ops_service_kit.listing import ListParams
from ops_store import isolation
from ops_store.schema import isolation_kind
from ops_store.team_scope import InstallScopeError

from .conftest import Models, past_the_call_log_policy

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
        page = await log.page(ListParams(), key_id=key_id)
        async with isolation.isolated_tx(models.engine, role=ROLE) as c:
            q = sa.text("SELECT count(*) FROM model_call_log WHERE key_id = :k")
            seen = (await c.execute(q, {"k": key_id})).scalar_one()
    assert (len(page.data), [t.calls for t in page.by_key], seen) == (1, [1], 1), "a tenant read another tenant's call"
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
        q = (
            sa.select(sa.func.count())
            .select_from(model_calls_untenanted)
            .where(model_calls_untenanted.c.id == row["id"])
        )
        kept = (await c.execute(q)).scalar_one()
    async with models.engine.connect() as c, past_the_call_log_policy(c):
        # The database's owner, past the policy: the log has no tenant-less row for the key.
        q = sa.select(sa.func.count()).select_from(model_call_log).where(model_call_log.c.key_id == key_id)
        logged = (await c.execute(q)).scalar_one()
    assert (kept, logged) == (1, 0)
    assert (await log.totals(key_id, datetime.now(UTC))).recent == 1, "the refusal still counts toward the rate"


async def test_a_call_row_and_its_keys_spend_commit_together_outside_a_request(models: Models) -> None:
    """From a task or a test, with no request transaction open: a spend write that fails leaves no row behind."""
    key_id = f"workflow:one-{uuid4().hex[:8]}"
    tenant, log = f"t_{uuid4().hex[:8]}", CallLog(models.engine)

    def refuse_spend(_c: object, _cur: object, statement: str, *_: object) -> None:
        if "model_key_spend" in statement and not statement.lstrip().upper().startswith("SELECT"):
            raise RuntimeError("the spend write failed")

    event.listen(models.engine.sync_engine, "before_cursor_execute", refuse_spend)
    try:
        with isolation.scope(tenant, None), pytest.raises(RuntimeError):
            await log.record(_row(key_id, tenant))
    finally:
        event.remove(models.engine.sync_engine, "before_cursor_execute", refuse_spend)
    with isolation.scope(tenant, None):
        page = await log.page(ListParams(), key_id=key_id)
    assert page.data == [], "a call row was kept with no spend counted for its key"


async def test_the_tenants_newest_calls_are_read_from_an_index_that_leads_with_the_tenant(models: Models) -> None:
    """Every read names the tenant (the policy adds it) and the page sorts by created_at: without an index that leads
    with both, a tenant's page scans every tenant's calls."""
    async with models.engine.connect() as c:
        found = await c.run_sync(lambda sc: sa.inspect(sc).get_indexes("model_call_log"))
    assert ["tenant_id", "created_at"] in [i["column_names"] for i in found], found
