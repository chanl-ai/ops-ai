"""Wrong-password counts on PostgreSQL and SQL Server, through the store: five at once for one person, or for one
address, count five and lock once (F3). The address count runs in install scope with no tenant, and both are an
insert of the row at zero then one counting UPDATE, which each database must keep exact under concurrency. And
`/v1/me`'s reads (outer joins, an embedded owner read, a null-ordered team list) answering the same on each."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa

from ops_access import ANY_TEAM
from ops_platform.store.identity import Client, IdentityStore
from ops_platform.store.me import MeStore, MyTeam
from ops_platform.store.roles import RoleStore, ensure_builtin_roles
from ops_platform.store.signin import SignInStore
from ops_platform.store.signin_secrets import SignInSecretStore
from ops_platform.store.tables import (
    members,
    role_assignments,
    signin_grants,
    signin_group_rules,
    signin_providers,
    signin_secrets,
    teams,
    tenants,
    users,
)
from ops_platform.store.tenancy import TenantDb
from ops_service_kit.credentials import credential_store
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.settings import Settings

WINDOW, UNTIL = "2000-01-01T00:00:00.000Z", "2999-01-01T00:00:00.000Z"


@pytest.fixture
async def store(store_url: str) -> AsyncIterator[SignInStore]:
    s = SignInStore(TenantDb.open(store_url))
    yield s
    await s.engine.dispose()


async def test_five_wrong_passwords_at_once_for_a_person_lock_once(store: SignInStore) -> None:
    tenant, user, now = new_id("ten"), new_id("usr"), now_iso()
    async with store.tenant_tx(tenant) as c:
        await c.execute(
            tenants.insert().values(id=tenant, name=tenant, status="active", allowed_domains=[], created_at=now)
        )
        await c.execute(
            users.insert().values(
                id=user, tenant_id=tenant, email=f"{user}@bank.test", name="Ana", status="active", created_at=now
            )
        )
    locked = await asyncio.gather(
        *(
            store.count_failure(
                tenant,
                user,
                at=now_iso(),
                request_id=new_id("req"),
                window_start=WINDOW,
                max_failures=5,
                lock_until=UNTIL,
            )
            for _ in range(5)
        )
    )
    assert sorted(locked) == [False, False, False, False, True], locked
    assert await store.locked_until(tenant, user, now=now_iso()) == UNTIL


async def test_five_wrong_passwords_at_once_for_an_address_lock_once(store: SignInStore) -> None:
    address = new_id("hash")
    locked = await asyncio.gather(
        *(
            store.count_email_failure(address, at=now_iso(), window_start=WINDOW, max_failures=5, lock_until=UNTIL)
            for _ in range(5)
        )
    )
    assert sorted(locked) == [False, False, False, False, True], locked
    assert await store.email_locked_until(address, now=now_iso()) == UNTIL
    await store.clear_email_failures(address)
    assert await store.email_locked_until(address, now=now_iso()) is None


async def test_me_reads_the_same_on_each_database(store_url: str) -> None:
    db = MeStore(TenantDb.open(store_url))
    tenant, user, mine, other, now = new_id("ten"), new_id("usr"), new_id("team"), new_id("team"), now_iso()
    try:
        async with db.tenant_tx(tenant) as c:
            await c.execute(
                tenants.insert().values(id=tenant, name="Harbor", status="active", allowed_domains=[], created_at=now)
            )
            await ensure_builtin_roles(c, tenant, at=now)
            await c.execute(
                users.insert().values(
                    id=user, tenant_id=tenant, email=f"{user}@bank.test", name="Ana", status="active", created_at=now
                )
            )
            for team in (mine, other):
                await c.execute(
                    teams.insert().values(
                        id=team, tenant_id=tenant, name=team, owner_groups=[], scope="owned", created_at=now
                    )
                )
            await c.execute(
                members.insert().values(
                    id=new_id("mem"), tenant_id=tenant, team_id=mine, user_id=user, email=f"{user}@bank.test",
                    role="builder", status="active", created_at=now, updated_at=now,
                )
            )  # fmt: skip
            for role in ("admin", "owner"):
                await c.execute(
                    role_assignments.insert().values(
                        id=new_id("ras"), tenant_id=tenant, subject_kind="person", subject_id=user, role_id=role,
                        team_id=ANY_TEAM, granted_by="test", reason="test", source="grant", created_at=now,
                    )
                )  # fmt: skip
        found = await db.read(tenant, user)
        assert found is not None
        assert (found.user.email, found.tenant_name, found.workspace.owner) == (f"{user}@bank.test", "Harbor", user)
        assert found.member_teams == [MyTeam(mine, mine, "builder")]
        assert found.other_teams == [MyTeam(other, other, None)]
        assert {a.role_id for a in found.holdings.assignments} == {"admin", "owner"}
        assert "admin" in found.grids and found.policies
        assert await db.read(tenant, new_id("usr")) is None
    finally:
        await db.engine.dispose()


async def test_a_provider_delete_takes_its_group_rules_and_grants(store: SignInStore) -> None:
    """A grant that names a group rule goes with its provider. SQL Server holds the rule key as NO ACTION (two cascade
    paths reach signin_grants), so this is the delete that would be refused there if the order were wrong."""
    tenant, user, team, member, provider, rule, now = (
        new_id("ten"), new_id("usr"), new_id("team"), new_id("mem"), new_id("sp"), new_id("sgr"), now_iso(),
    )  # fmt: skip
    async with store.tenant_tx(tenant) as c:
        await c.execute(
            tenants.insert().values(id=tenant, name=tenant, status="active", allowed_domains=[], created_at=now)
        )
        await c.execute(
            users.insert().values(
                id=user, tenant_id=tenant, email=f"{user}@bank.test", name="Ana", status="active", created_at=now
            )
        )
        await c.execute(
            teams.insert().values(id=team, tenant_id=tenant, name=team, owner_groups=[], scope="owned", created_at=now)
        )
        await c.execute(
            members.insert().values(
                id=member, tenant_id=tenant, team_id=team, user_id=user, email=f"{user}@bank.test", role="builder",
                status="active", created_at=now, updated_at=now,
            )
        )  # fmt: skip
        await c.execute(
            signin_providers.insert().values(
                id=provider, tenant_id=tenant, kind="saml", label="Okta", enabled=True, config={}, created_at=now,
                updated_at=now,
            )
        )  # fmt: skip
        await c.execute(
            signin_group_rules.insert().values(
                id=rule, tenant_id=tenant, provider_id=provider, group_value="ops", team_id=team, role="builder",
                created_at=now, created_by=user,
            )
        )  # fmt: skip
        await c.execute(
            signin_grants.insert().values(
                id=new_id("sgt"), tenant_id=tenant, member_id=member, provider_id=provider, rule_id=rule, why="group",
                granted_at=now,
            )
        )  # fmt: skip
    deleted = await store.delete_provider(tenant, provider, actor=user, at=now, request_id=new_id("req"))
    async with store.tenant_tx(tenant) as c:
        left = [
            (await c.execute(sa.select(sa.func.count()).select_from(t))).scalar_one()
            for t in (signin_providers, signin_group_rules, signin_grants)
        ]
    assert (deleted, left) == (True, [0, 0, 0])


async def test_install_rows_and_deletes_that_return_a_row_on_each_database(store: SignInStore) -> None:
    """The assistant registry and address counts, read and written with no tenant, and the two deletes that read back
    what they removed (a given role, a sign-in secret), which SQL Server writes as OUTPUT."""
    identity, roles = IdentityStore(store), RoleStore(store)
    secrets = SignInSecretStore(store, credential_store(Settings()))
    tenant, user, team, client, now = new_id("ten"), new_id("usr"), new_id("team"), new_id("cli"), now_iso()
    await identity.register_client(
        Client(client, "Desk", ["https://desk.test/cb"], None, None), at=now, stale_before=WINDOW
    )
    found = await identity.client(client)
    assert found is not None
    assert (found.name, found.redirect_uris, found.consented_at) == ("Desk", ["https://desk.test/cb"], None)
    address = new_id("ip")
    counts = [(await identity.count_address("token", address, at=now, window_start=WINDOW))[0] for _ in range(2)]
    assert counts == [1, 2]
    assert await identity.clients_of_tenant(tenant) == 0
    async with store.tenant_tx(tenant) as c:
        await c.execute(
            tenants.insert().values(id=tenant, name=tenant, status="active", allowed_domains=[], created_at=now)
        )
        await ensure_builtin_roles(c, tenant, at=now)
        await c.execute(
            teams.insert().values(id=team, tenant_id=tenant, name=team, owner_groups=[], scope="owned", created_at=now)
        )
        await c.execute(
            signin_secrets.insert().values(
                tenant_id=tenant, name="okta", ciphertext="sealed", version=1, created_by=user, created_at=now
            )
        )
    grant = await roles.grant(tenant, user, "builder", team, by=user, request_id=new_id("req"))
    assert await roles.ungrant(tenant, grant, by=user, request_id=new_id("req")) is True
    assert await roles.ungrant(tenant, grant, by=user, request_id=new_id("req")) is False
    assert await secrets.delete(tenant, "okta", by=user, request_id=new_id("req")) is True
    assert await secrets.delete(tenant, "okta", by=user, request_id=new_id("req")) is False
