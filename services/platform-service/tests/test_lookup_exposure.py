"""What the tenant role can see before and after it knows the tenant, on PostgreSQL and SQL Server.

Connected as the tenant role (`ops_platform_tenant` on PostgreSQL, the runtime user `ops_platform_runtime` on SQL
Server, impersonated here since the SQL Server rig connects as the administrator): another tenant's session, API key and
password reset never come back from a direct SELECT, in a tenant's transaction or in none; each lookup function returns
the one row its exact key names and nothing for a near miss; and the tenant role cannot become the principal the
lookups run as. Then the lookups' values read the same on both databases."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_platform.store.lookups import KEY, PASSWORD_RESET, SESSION, SIGNIN_SP, Lookup, lookup
from ops_platform.store.tables import api_keys, password_resets, sessions, signin_providers, teams, tenants, users
from ops_platform.store.tenancy import SESSION_LOOKUP, TenantDb
from ops_service_kit.ids import new_id, now_iso
from ops_store.dialect import dialect_of

RUNTIME = "ops_platform_runtime"


@pytest.fixture
async def db(store_url: str) -> AsyncIterator[TenantDb]:
    d = TenantDb.open(store_url)
    yield d
    await d.engine.dispose()


@asynccontextmanager
async def as_tenant_role(db: TenantDb, tenant: str | None) -> AsyncGenerator[AsyncConnection]:
    """A transaction as the tenant role, in `tenant` or (None) in no tenant, as the lookups run."""
    async with db.tenant_tx(tenant) if tenant else db.system_tx(SESSION_LOOKUP) as c:
        mssql = dialect_of(c) == "mssql"
        if mssql:
            await c.execute(sa.text(f"EXECUTE AS USER = N'{RUNTIME}'"))
        yield c
        if mssql:
            await c.execute(sa.text("REVERT"))


async def _tenant_with_rows(db: TenantDb) -> dict[str, str]:
    tenant, now = new_id("ten"), now_iso()
    ids = {
        "tenant": tenant,
        "session": new_id("ses"),
        "key": new_id("key"),
        "reset": new_id("hash"),
        "user": new_id("usr"),
        "team": new_id("team"),
    }
    async with db.tenant_tx(tenant) as c:
        await c.execute(
            tenants.insert().values(id=tenant, name=tenant, status="active", allowed_domains=[], created_at=now)
        )
        await c.execute(
            users.insert().values(
                id=ids["user"],
                tenant_id=tenant,
                email=f"{ids['user']}@bank.test",
                name="Ana",
                status="active",
                created_at=now,
            )
        )
        await c.execute(
            teams.insert().values(
                id=ids["team"], tenant_id=tenant, name="Ops", owner_groups=[], scope="owned", created_at=now
            )
        )
        await c.execute(
            sessions.insert().values(
                id=ids["session"], tenant_id=tenant, user_id=ids["user"], auth_method="password",
                refresh_hash=new_id("hash"), expires_at="2999-01-01T00:00:00.000Z", last_seen_at=now, created_at=now,
            )
        )  # fmt: skip
        await c.execute(
            api_keys.insert().values(
                id=new_id("kid"), tenant_id=tenant, team_id=ids["team"], name="ci", prefix=ids["key"],
                secret_hash=new_id("hash"), scopes=["read", "write"], created_by=ids["user"], created_at=now,
            )
        )  # fmt: skip
        await c.execute(
            password_resets.insert().values(
                id=new_id("pwr"), tenant_id=tenant, user_id=ids["user"], token_hash=ids["reset"], created_at=now,
                expires_at="2999-01-01T00:00:00.000Z",
            )
        )  # fmt: skip
    return ids


# (lookup, the row's key, the table, its key column)
CASES = [
    (SESSION, "session", sessions, sessions.c.id),
    (KEY, "key", api_keys, api_keys.c.prefix),
    (PASSWORD_RESET, "reset", password_resets, password_resets.c.token_hash),
]


@pytest.mark.parametrize(("fn", "kind", "table", "column"), CASES, ids=[c[1] for c in CASES])
async def test_the_tenant_role_reads_another_tenants_row_only_through_its_exact_key(
    db: TenantDb, fn: Lookup, kind: str, table: sa.Table, column: sa.Column[str]
) -> None:
    mine, theirs = await _tenant_with_rows(db), await _tenant_with_rows(db)
    key = theirs[kind]
    extra = ("2000-01-01T00:00:00.000Z",) if fn is KEY else ()
    for tenant in (mine["tenant"], None):
        async with as_tenant_role(db, tenant) as c:
            direct = (await c.execute(sa.select(sa.func.count()).select_from(table).where(column == key))).scalar()
            every = (await c.execute(sa.select(sa.func.count()).select_from(table))).scalar()
        assert direct == 0, (kind, tenant)
        assert every == (0 if tenant is None else 1), (kind, tenant)
    async with as_tenant_role(db, None) as c:
        found = await lookup(c, fn, key, *extra)
        misses = [await lookup(c, fn, k, *extra) for k in (key[:-1], key.upper(), key + "x", "%", f"{key[:4]}%")]
    tenant_of = found[0].tenant_id if len(found) == 1 else None
    assert (len(found), tenant_of) == (1, theirs["tenant"])
    assert misses == [[]] * 5


async def test_the_tenant_role_cannot_become_the_lookups_principal(db: TenantDb) -> None:
    """The lookups run as `ops_platform_system` on SQL Server and are owned by `ops_platform_lookup` on PostgreSQL;
    the tenant role may switch to neither, so it reads rows past its tenant only through a function's exact key."""
    async with as_tenant_role(db, None) as c:
        if dialect_of(c) == "postgresql":
            # The test login is a superuser, which may SET ROLE to anything; membership is what a runtime login has.
            q = "SELECT pg_has_role('ops_platform_tenant', 'ops_platform_lookup', 'MEMBER')"
            assert (await c.execute(sa.text(q))).scalar() is False
            return
        async with db.attempt(c):
            with pytest.raises(DBAPIError):
                await c.execute(sa.text("EXECUTE AS USER = N'ops_platform_system'"))


async def test_the_lookups_return_the_same_values_on_each_database(db: TenantDb) -> None:
    """A JSON list comes back as a list and a condition as a flag; a provider's tiles are on unless set false."""
    ids, now = await _tenant_with_rows(db), now_iso()
    tenant = ids["tenant"]
    sp = {flag: new_id("sp") for flag in ("absent", "on", "off")}
    configs = {"absent": {}, "on": {"tiles": True}, "off": {"tiles": False}}
    async with db.tenant_tx(tenant) as c:
        for flag, sp_id in sp.items():
            await c.execute(
                signin_providers.insert().values(
                    id=new_id("prv"), tenant_id=tenant, kind="saml", label=flag, enabled=True, config=configs[flag],
                    created_at=now, updated_at=now, sp_id=sp_id,
                )
            )  # fmt: skip
        await c.execute(api_keys.update().where(api_keys.c.prefix == ids["key"]).values(revoked_at=now))
    async with as_tenant_role(db, None) as c:
        (key,) = await lookup(c, KEY, ids["key"], "2000-01-01T00:00:00.000Z")
        tiles = {flag: (await lookup(c, SIGNIN_SP, sp_id))[0].tiles for flag, sp_id in sp.items()}
    assert (key.scopes, key.usable) == (["read", "write"], False)
    assert tiles == {"absent": True, "on": True, "off": False}
