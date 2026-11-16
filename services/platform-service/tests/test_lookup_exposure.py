"""What the tenant role can see before and after it knows the tenant, on PostgreSQL and SQL Server.

Connected as the tenant role (`ops_platform_tenant` on PostgreSQL, the runtime user `ops_platform_runtime` on SQL
Server, impersonated here since the SQL Server rig connects as the administrator): another tenant's session, API key and
password reset never come back from a direct SELECT, in a tenant's transaction or in none; each lookup function returns
the one row its exact key names and nothing for a near miss; and the tenant role cannot become the principal the
lookups run as. Then the lookups' values read the same on both databases."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from ops_platform.store.identity import IdentityStore
from ops_platform.store.lifecycle import LifecycleStore
from ops_platform.store.lookups import KEY, PASSWORD_RESET, SESSION, Lookup, lookup
from ops_platform.store.members import TeamStore
from ops_platform.store.signin import SignInStore
from ops_platform.store.tables import (
    api_keys,
    members,
    password_credentials,
    password_resets,
    sessions,
    signin_flows,
    signin_providers,
    teams,
    tenants,
    users,
)
from ops_platform.store.tenancy import TenantDb
from ops_service_kit.ids import new_id, now_iso
from ops_store.dialect import dialect_of

from .conftest import as_tenant_role


@pytest.fixture
async def db(store_url: str) -> AsyncIterator[TenantDb]:
    d = TenantDb.open(store_url)
    yield d
    await d.engine.dispose()


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


async def test_the_stores_read_the_same_through_the_lookups_on_each_database(db: TenantDb) -> None:
    """Through the stores' own calls: a JSON list comes back as a list and a condition as a flag; a provider's tiles
    are on unless set false; the session, the person by email, the team and the watched providers are found; an
    invitation reads with its team and domains, a sign-in flow by its state and by its handoff, a reset is spent once
    and sets the password, and a workspace closed past the window is due for the purge."""
    ids, now = await _tenant_with_rows(db), now_iso()
    tenant = ids["tenant"]
    sp = {flag: new_id("sp") for flag in ("absent", "on", "off")}
    configs = {"absent": {}, "on": {"tiles": True}, "off": {"tiles": False}}
    providers: dict[str, str] = {}
    async with db.tenant_tx(tenant) as c:
        for flag, sp_id in sp.items():
            providers[flag] = new_id("prv")
            await c.execute(
                signin_providers.insert().values(
                    id=providers[flag], tenant_id=tenant, kind="saml", label=flag, enabled=True, config=configs[flag],
                    created_at=now, updated_at=now, sp_id=sp_id,
                )
            )  # fmt: skip
        await c.execute(api_keys.update().where(api_keys.c.prefix == ids["key"]).values(revoked_at=now))
    identity, signin = IdentityStore(db), SignInStore(db)
    key = await identity.key(ids["key"])
    assert key is not None
    assert (key.tenant_id, key.scopes, key.usable) == (tenant, ["read", "write"], False)
    assert {flag: getattr(await signin.sp(sp_id), "tiles", None) for flag, sp_id in sp.items()} == {
        "absent": True, "on": True, "off": False,
    }  # fmt: skip
    session = await identity.session(ids["session"])
    assert session is not None
    assert (session.tenant_id, session.user_id) == (tenant, ids["user"])
    assert [u.id for u in await identity.users_by_email(f"{ids['user'].upper()}@BANK.TEST")] == [ids["user"]]
    assert await identity.team_tenant(ids["team"]) == (tenant, "active")
    watched = {p for t, p in await signin.watched() if t == tenant}
    assert watched == set(providers.values())
    invite, state, handoff = new_id("hash"), new_id("hash"), new_id("hash")
    async with db.tenant_tx(tenant) as c:
        await c.execute(
            members.insert().values(
                id=new_id("mem"), tenant_id=tenant, team_id=ids["team"], email="new@bank.test", role="builder",
                status="invited", created_at=now, updated_at=now, invite_token_hash=invite,
                invite_expires_at="2999-01-01T00:00:00.000Z",
            )
        )  # fmt: skip
        await c.execute(tenants.update().where(tenants.c.id == tenant).values(allowed_domains=["bank.test"]))
        # With SAML on, a reset is spent only while passwords are on too.
        await c.execute(
            signin_providers.insert().values(
                id=new_id("prv"), tenant_id=tenant, kind="password", label="Password", enabled=True, config={},
                created_at=now, updated_at=now,
            )
        )  # fmt: skip
        await c.execute(
            signin_flows.insert().values(
                id=new_id("flw"), tenant_id=tenant, provider_id=providers["on"], purpose="sign_in", state_hash=state,
                browser_hash=new_id("b"), created_at=now, expires_at="2999-01-01T00:00:00.000Z", handoff_hash=handoff,
            )
        )  # fmt: skip
    found = await TeamStore(db).invite_by_hash(invite)
    assert found is not None
    assert (found.tenant_id, found.team, found.status, found.allowed_domains) == (
        tenant, "Ops", "invited", ["bank.test"],
    )  # fmt: skip
    by_state, by_handoff = await signin.flow_by_state(state), await signin.flow_by_handoff(handoff)
    assert by_state is not None and by_handoff is not None
    assert (by_state.tenant_id, by_state.provider_id, by_handoff.id) == (tenant, providers["on"], by_state.id)
    assert await signin.flow_by_state(state + "x") is None
    spent = [await signin.use_reset(ids["reset"], "pbkdf2$x", at=now, request_id=new_id("req")) for _ in range(2)]
    assert spent == [(tenant, ids["user"]), None]
    async with db.tenant_tx(tenant) as c:
        held = (await c.execute(sa.select(password_credentials.c.hash))).scalars().all()
        await c.execute(tenants.update().where(tenants.c.id == tenant).values(status="closed", closed_at=now))
    assert held == ["pbkdf2$x"]
    lifecycle = LifecycleStore(db)
    assert tenant not in await lifecycle.purge_due(restore_days=30)
    assert tenant in await lifecycle.purge_due(restore_days=30, now=datetime.now(UTC) + timedelta(days=31))
