"""Row-level security on every platform table (I2), on PostgreSQL and SQL Server, by failure mode: a tenant reads
another tenant's rows, a query with no tenant set reads anything, a write lands rows for another tenant, a row points at
another tenant's team or user, and the tenant role changes the audit log. Each tenant also reads its own row, which
proves the row it cannot see in the other tenant exists; on PostgreSQL the superuser counts both as well."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_platform.store.tables import (
    TENANT_TABLES,
    api_keys,
    audit_entries,
    members,
    password_credentials,
    password_resets,
    policies,
    role_assignments,
    role_permissions,
    roles,
    sessions,
    signin_domains,
    signin_flows,
    signin_identities,
    signin_providers,
    teams,
    tenants,
    users,
)
from ops_platform.store.tenancy import ROLE, TenantDb
from ops_service_kit.ids import new_id, now_iso
from ops_store.isolation import NoTenantError
from ops_store.schema import isolated_tables

from .conftest import RUNTIME, as_tenant_role, seed_tx


async def seed(engine: AsyncEngine) -> tuple[str, str]:
    """Two tenants with one row in every table, each written past the row policies in its own tenant (`seed_tx`); the
    role tables get one custom role each, since built-in roles are not seeded here."""
    a, b = new_id("ten"), new_id("ten")
    now = now_iso()
    for t in (a, b):
        async with seed_tx(engine, t) as c:
            team, user = new_id("team"), new_id("usr")
            await c.execute(tenants.insert().values(id=t, name=t, status="active", allowed_domains=[], created_at=now))
            await c.execute(
                teams.insert().values(id=team, tenant_id=t, name="Ops", owner_groups=[], scope="all", created_at=now)
            )
            await c.execute(
                users.insert().values(
                    id=user, tenant_id=t, email=f"{user}@bank.test", name="A", status="active", created_at=now
                )
            )
            await c.execute(
                members.insert().values(
                    id=new_id("mem"),
                    tenant_id=t,
                    team_id=team,
                    user_id=user,
                    email=f"{user}@bank.test",
                    role="admin",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            await c.execute(
                api_keys.insert().values(
                    id=new_id("key"),
                    tenant_id=t,
                    team_id=team,
                    name="ci",
                    prefix=new_id("pfx"),
                    secret_hash=new_id("h"),
                    scopes=["read"],
                    created_by=user,
                    created_at=now,
                )
            )
            await c.execute(
                sessions.insert().values(
                    id=new_id("ses"),
                    tenant_id=t,
                    user_id=user,
                    auth_method="dev",
                    refresh_hash=new_id("r"),
                    expires_at=now,
                    created_at=now,
                    last_seen_at=now,
                )
            )
            await c.execute(
                audit_entries.insert().values(
                    id=new_id("aud"),
                    tenant_id=t,
                    team_id=team,
                    actor=user,
                    action="test.seed",
                    target_kind="team",
                    target_id=team,
                    request_id=new_id("req"),
                    at=now,
                    detail={},
                )
            )
            await c.execute(
                roles.insert().values(
                    tenant_id=t, id="custom", name="Custom", builtin=False, description="", created_at=now
                )
            )
            await c.execute(
                role_permissions.insert().values(
                    tenant_id=t, role_id="custom", area="agents", action="view", scope="all"
                )
            )
            await c.execute(
                role_assignments.insert().values(
                    id=new_id("ras"),
                    tenant_id=t,
                    subject_kind="person",
                    subject_id=user,
                    role_id="custom",
                    team_id=team,
                    granted_by=user,
                    reason="test",
                    source="grant",
                    created_at=now,
                )
            )
            provider = new_id("sip")
            await c.execute(
                signin_providers.insert().values(
                    id=provider, tenant_id=t, kind="oidc", label="SSO", enabled=True, config={}, created_at=now,
                    updated_at=now,
                )
            )  # fmt: skip
            await c.execute(
                signin_domains.insert().values(
                    domain=f"{t}.test", tenant_id=t, provider_id=provider, created_at=now, token="tok", verified_at=now
                )
            )
            await c.execute(
                signin_identities.insert().values(
                    id=new_id("sid"), tenant_id=t, provider_id=provider, subject="s", user_id=user, created_at=now,
                    last_used_at=now,
                )
            )  # fmt: skip
            await c.execute(
                signin_flows.insert().values(
                    id=new_id("flw"), tenant_id=t, provider_id=provider, purpose="sign_in", state_hash=new_id("h"),
                    browser_hash=new_id("b"), created_at=now, expires_at=now,
                )
            )  # fmt: skip
            await c.execute(password_credentials.insert().values(user_id=user, tenant_id=t, hash="x", updated_at=now))
            await c.execute(
                password_resets.insert().values(
                    id=new_id("prs"), tenant_id=t, user_id=user, token_hash=new_id("t"), created_at=now, expires_at=now
                )
            )
            await c.execute(
                policies.insert().values(tenant_id=t, key="stepUp", value=True, updated_by="x", updated_at=now)
            )
    return a, b


async def test_every_table_is_isolated_by_the_database(engine: AsyncEngine) -> None:
    """PostgreSQL: forced row-level security, which filters the table owner too (a deployment connecting as the owner
    would not be filtered with RLS enabled alone). SQL Server: an enabled security policy. Read from the catalog."""
    names = [t.name for t in (*TENANT_TABLES, tenants)]
    async with engine.connect() as c:
        held = await c.run_sync(isolated_tables)
    assert {n: held.get(n) for n in names} == dict.fromkeys(names, "tenant")


async def test_a_tenant_sees_only_its_own_rows(engine: AsyncEngine) -> None:
    a, b = await seed(engine)
    db = TenantDb(engine)
    for table in (*TENANT_TABLES, tenants):
        col = tenants.c.id if table is tenants else table.c.tenant_id

        def count(tenant: str, col: sa.Column[str] = col, table: sa.Table = table) -> sa.Select[int]:
            return sa.select(sa.func.count()).select_from(table).where(col == tenant)

        for mine, theirs in ((a, b), (b, a)):
            async with db.tenant_tx(mine) as c:
                seen = [int((await c.execute(count(t))).scalar_one()) for t in (mine, theirs)]
            assert seen == [1, 0], f"{table.name}: tenant {mine} sees its row only"
        if engine.dialect.name == "postgresql":
            async with engine.connect() as c:
                both = sa.select(sa.func.count()).select_from(table).where(col.in_([a, b]))
                assert int((await c.execute(both)).scalar_one()) == 2, f"{table.name}: both rows exist"


async def test_no_tenant_set_sees_nothing(engine: AsyncEngine) -> None:
    a, b = await seed(engine)
    with pytest.raises(NoTenantError):
        async with TenantDb(engine).tenant_tx(None):
            pytest.fail("a transaction opened with no tenant")
    # Below the store: the tenant role (the runtime user on SQL Server) with no tenant set sees no row at all.
    mssql = engine.dialect.name == "mssql"
    async with engine.begin() as c:
        await c.execute(sa.text(f"EXECUTE AS USER = N'{RUNTIME}'" if mssql else f"SET LOCAL ROLE {ROLE}"))
        for table in TENANT_TABLES:
            q = sa.select(sa.func.count()).select_from(table).where(table.c.tenant_id.in_([a, b]))
            assert int((await c.execute(q)).scalar_one()) == 0, f"{table.name}: unset tenant sees nothing"
        if mssql:
            await c.execute(sa.text("REVERT"))


async def test_a_write_for_another_tenant_is_refused(engine: AsyncEngine) -> None:
    a, b = await seed(engine)
    with pytest.raises(DBAPIError) as e:
        async with TenantDb(engine).tenant_tx(a) as c:
            await c.execute(
                teams.insert().values(
                    id=new_id("team"), tenant_id=b, name="x", owner_groups=[], scope="all", created_at=now_iso()
                )
            )
    assert ("block predicate" if engine.dialect.name == "mssql" else "row-level security") in str(e.value)


async def _ids(engine: AsyncEngine, tenant: str) -> tuple[str, str]:
    """A team and a user of `tenant`, read in its own tenant."""
    async with TenantDb(engine).tenant_tx(tenant) as c:
        team = (await c.execute(sa.select(teams.c.id).where(teams.c.tenant_id == tenant))).scalar_one()
        user = (await c.execute(sa.select(users.c.id).where(users.c.tenant_id == tenant))).scalar_one()
    return team, user


async def test_a_row_cannot_point_at_another_tenants_team_or_user(engine: AsyncEngine) -> None:
    """RLS checks a row's own tenant_id only, and foreign keys are checked without RLS, so a single-column reference
    would let tenant A's row attach to tenant B's team or user."""
    a, b = await seed(engine)
    own_team, own_user = await _ids(engine, a)
    their_team, their_user = await _ids(engine, b)
    now = now_iso()
    attempts = {
        "members.team_id": members.insert().values(
            id=new_id("mem"),
            tenant_id=a,
            team_id=their_team,
            user_id=own_user,
            email="x@bank.test",
            role="viewer",
            status="active",
            created_at=now,
            updated_at=now,
        ),
        "members.user_id": members.insert().values(
            id=new_id("mem"),
            tenant_id=a,
            team_id=own_team,
            user_id=their_user,
            email="y@bank.test",
            role="viewer",
            status="active",
            created_at=now,
            updated_at=now,
        ),
        "api_keys.team_id": api_keys.insert().values(
            id=new_id("key"),
            tenant_id=a,
            team_id=their_team,
            name="x",
            prefix=new_id("pfx"),
            secret_hash="h",
            scopes=["read"],
            created_by=own_user,
            created_at=now,
        ),
        "api_keys.created_by": api_keys.insert().values(
            id=new_id("key"),
            tenant_id=a,
            team_id=own_team,
            name="x",
            prefix=new_id("pfx"),
            secret_hash="h",
            scopes=["read"],
            created_by=their_user,
            created_at=now,
        ),
        "sessions.user_id": sessions.insert().values(
            id=new_id("ses"),
            tenant_id=a,
            user_id=their_user,
            auth_method="dev",
            refresh_hash=new_id("r"),
            expires_at=now,
            created_at=now,
            last_seen_at=now,
        ),
        "audit_entries.team_id": audit_entries.insert().values(
            id=new_id("aud"),
            tenant_id=a,
            team_id=their_team,
            actor=own_user,
            action="x",
            target_kind="team",
            target_id=their_team,
            request_id=new_id("req"),
            at=now,
            detail={},
        ),
    }
    db = TenantDb(engine)
    for where, insert in attempts.items():
        with pytest.raises(DBAPIError) as e:
            async with db.tenant_tx(a) as c:
                await c.execute(insert)
        assert "foreign key" in str(e.value).lower(), where


async def test_the_tenant_role_cannot_change_or_remove_an_audit_entry(engine: AsyncEngine) -> None:
    """As the role the service runs as: `ops_platform_tenant` on PostgreSQL, the runtime user on SQL Server (the rig
    connects as the administrator, who may do anything, so it is impersonated)."""
    a, _ = await seed(engine)
    db = TenantDb(engine)
    for statement in (
        audit_entries.update().where(audit_entries.c.tenant_id == a).values(action="edited"),
        audit_entries.delete().where(audit_entries.c.tenant_id == a),
    ):
        async with as_tenant_role(db, a) as c:
            with pytest.raises(DBAPIError) as e:
                async with db.attempt(c):
                    await c.execute(statement)
            left = (await c.execute(sa.select(sa.func.count()).select_from(audit_entries))).scalar_one()
        assert "permission" in str(e.value).lower() and "denied" in str(e.value).lower()
        assert left == 1
