"""A deleted sign-in leaves no value behind in the credential store (c-616 C7 follow-up): with a vault, a row that goes
without telling the store leaves its token in the vault for good. Run on the memory vault, by failure mode: a person
disconnects, a connection is deleted with sign-ins on it, and a member leaves the team."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_access.platform_events import MEMBER_REMOVED
from ops_policy import InMemoryVault
from ops_tools.platform_events import member_removed_handlers
from ops_tools.store.connections import ConnectionStore, connection_tokens

from .conftest import credentials

# The person-credentials app and its fake ledger, fixtures, used by name below; its ledger connection and key steps.
from .test_person_credentials import (  # noqa: F401
    JAMES_P,
    TEAM,
    _give,  # pyright: ignore[reportPrivateUsage]
    _ledger,  # pyright: ignore[reportPrivateUsage]
    client,  # pyright: ignore[reportUnusedImport]
    ledger,  # pyright: ignore[reportUnusedImport]
)
from .test_review_decisions import person


@pytest.fixture(autouse=True)
def memory_vault(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Before the app is built, so every value of these tests lives in the vault and not in the rows.
    monkeypatch.setenv("OPS_CREDENTIAL_STORE", "memory")
    yield


async def _refs(engine: AsyncEngine, conn: str) -> list[str]:
    async with engine.connect() as c:
        rows = await c.execute(
            sa.select(connection_tokens.c.access_ct).where(connection_tokens.c.connection_id == conn)
        )
        return [str(r[0]) for r in rows]


async def _james_key(client: httpx.AsyncClient, engine: AsyncEngine, tenant: str) -> tuple[str, str]:  # noqa: F811
    conn = await _ledger(client, tenant)
    assert (await _give(client, tenant, conn, JAMES_P, key="key-james")).status_code == 200
    (ref,) = await _refs(engine, conn)
    assert InMemoryVault().holds(ref), "the key lives in the vault, the row holds its reference"
    return conn, ref


async def test_disconnecting_drops_the_persons_key_from_the_vault(
    client: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    conn, ref = await _james_key(client, engine, tenant)
    gone = await client.delete(
        f"/v1/me/connections/{conn}", params={"environment": "test"}, headers=person(tenant, *JAMES_P)
    )
    assert gone.status_code == 204, gone.text
    assert not InMemoryVault().holds(ref), "a disconnected key stays in the vault"


async def test_deleting_a_connection_drops_every_sign_in_on_it(
    client: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    conn, ref = await _james_key(client, engine, tenant)
    deleted = await client.delete(f"/v1/connections/{conn}", headers=person(tenant, "Priya Shah", {TEAM: "admin"}))
    assert deleted.status_code == 204, deleted.text
    assert not InMemoryVault().holds(ref), "a deleted connection's sign-ins stay in the vault"


async def test_a_member_who_leaves_takes_their_keys_out_of_the_vault(
    client: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    conn, ref = await _james_key(client, engine, tenant)
    forget = member_removed_handlers(ConnectionStore(engine), credentials())[MEMBER_REMOVED]
    assert await forget.act(tenant, TEAM, {"personId": "usr_james"}) == 1
    assert await _refs(engine, conn) == [] and not InMemoryVault().holds(ref), "a leaver's key stays in the vault"
