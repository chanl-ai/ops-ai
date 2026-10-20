"""Row-level security on every platform table (I2), by failure mode: a tenant reads another tenant's rows, a query with
no tenant set reads anything, and a write lands rows for another tenant. The compose user is a superuser and bypasses
RLS, so each test also counts as the superuser to prove the rows it cannot see exist."""

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


async def seed(engine: AsyncEngine) -> tuple[str, str]:
    """Two tenants with one row in every table, written as the superuser (which RLS does not filter); the role tables
    get one custom role each, since built-in roles are not seeded here."""
    a, b = new_id("ten"), new_id("ten")
    now = now_iso()
    async with engine.begin() as c:
        for t in (a, b):
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


async def test_every_table_forces_row_level_security(engine: AsyncEngine) -> None:
    """FORCE filters the table owner too. The tests above run as the tenant role, which owns nothing, so they pass
    without it; a deployment connecting as the owner would not. Read from the catalog instead."""
    names = [t.name for t in (*TENANT_TABLES, tenants)]
    q = sa.text("select relname, relrowsecurity, relforcerowsecurity from pg_class where relname = any(:n)")
    async with engine.connect() as c:
        rows = {r[0]: (r[1], r[2]) for r in await c.execute(q, {"n": names})}
    assert rows == dict.fromkeys(names, (True, True))


async def test_a_tenant_sees_only_its_own_rows(engine: AsyncEngine) -> None:
    a, b = await seed(engine)
    db = TenantDb(engine)
    for table in (*TENANT_TABLES, tenants):
        col = tenants.c.id if table is tenants else table.c.tenant_id
        unfiltered = sa.select(sa.func.count()).select_from(table).where(col.in_([a, b]))
        async with db.tenant_tx(a) as c:
            assert int((await c.execute(unfiltered)).scalar_one()) == 1, f"{table.name}: tenant A sees only its row"
        async with db.tenant_tx(b) as c:
            assert int((await c.execute(unfiltered)).scalar_one()) == 1, f"{table.name}: tenant B sees only its row"
        async with engine.connect() as c:
            assert int((await c.execute(unfiltered)).scalar_one()) == 2, f"{table.name}: both rows exist"


async def test_no_tenant_set_sees_nothing(engine: AsyncEngine) -> None:
    a, b = await seed(engine)
    with pytest.raises(NoTenantError):
        async with TenantDb(engine).tenant_tx(None):
            pytest.fail("a transaction opened with no tenant")
    # Below the store: the tenant role with app.tenant_id unset sees no row at all.
    async with engine.begin() as c:
        await c.execute(sa.text(f"SET LOCAL ROLE {ROLE}"))
        for table in TENANT_TABLES:
            q = sa.select(sa.func.count()).select_from(table).where(table.c.tenant_id.in_([a, b]))
            assert int((await c.execute(q)).scalar_one()) == 0, f"{table.name}: unset tenant sees nothing"


async def test_a_write_for_another_tenant_is_refused(engine: AsyncEngine) -> None:
    a, b = await seed(engine)
    with pytest.raises(DBAPIError) as e:
        async with TenantDb(engine).tenant_tx(a) as c:
            await c.execute(
                teams.insert().values(
                    id=new_id("team"), tenant_id=b, name="x", owner_groups=[], scope="all", created_at=now_iso()
                )
            )
    assert "row-level security" in str(e.value)


async def _ids(engine: AsyncEngine, tenant: str) -> tuple[str, str]:
    """A team and a user of `tenant`, read as the superuser."""
    async with engine.connect() as c:
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
        assert "foreign key" in str(e.value), where


async def test_the_tenant_role_cannot_change_or_remove_an_audit_entry(engine: AsyncEngine) -> None:
    a, _ = await seed(engine)
    db = TenantDb(engine)
    for statement in (
        audit_entries.update().where(audit_entries.c.tenant_id == a).values(action="edited"),
        audit_entries.delete().where(audit_entries.c.tenant_id == a),
    ):
        with pytest.raises(DBAPIError) as e:
            async with db.tenant_tx(a) as c:
                await c.execute(statement)
        assert "permission denied" in str(e.value)
