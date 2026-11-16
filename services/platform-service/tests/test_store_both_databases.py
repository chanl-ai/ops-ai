"""Wrong-password counts on PostgreSQL and SQL Server, through the store: five at once for one person, or for one
address, count five and lock once (F3). The address count runs in install scope with no tenant, and both are an
insert of the row at zero then one counting UPDATE, which each database must keep exact under concurrency."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from ops_platform.store.signin import SignInStore
from ops_platform.store.tables import tenants, users
from ops_platform.store.tenancy import TenantDb
from ops_service_kit.ids import new_id, now_iso

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
