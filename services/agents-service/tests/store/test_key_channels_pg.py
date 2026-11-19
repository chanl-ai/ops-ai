"""The Channels list's store on the migrated test database under the tenant role, by failure mode: a key's threads
are counted by the `startedBy` their metadata holds (a JSON read SQLite answers more loosely), and another tenant's
thread under the same key id counts nothing; a resync of one tenant's keys buries or changes another tenant's copy
rows, or keeps a revoked or vanished key listed; rows of equal names repeat or skip between pages, or a total counts
another tenant's copy. Also run on SQL Server (`make mssql-remote-test`)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.api_key_copy import PATH, resync_all
from ops_agents.store.channel_list import ChannelList
from ops_agents.store.graphs import GraphStore
from ops_agents.store.mailboxes import MailboxRow, MailboxStore
from ops_agents.store.tenancy import current_tenant, tenant_scope
from ops_service_kit.http import Json
from ops_service_kit.listing import ListParams


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


def summary(kid: str, *, name: str = "CI", status: str = "active", team: str = "team_ops") -> dict[str, Any]:
    return {
        "id": kid,
        "name": name,
        "prefix": kid,
        "teamId": team,
        "status": status,
        "target": None,
        "lastUsedAt": None,
        "expiresAt": None,
        "createdAt": "2026-10-01T00:00:00.000Z",
    }


class Platform:
    """platform-service's `GET /v1/api-key-summaries`: the keys of the tenant the token is minted for."""

    def __init__(self, keys: dict[str, list[dict[str, Any]]]) -> None:
        self.keys = keys

    async def get(self, path: str, **_: Any) -> Any:
        assert path == PATH
        return self.keys[current_tenant()]


async def resync(engine: AsyncEngine, keys: dict[str, list[dict[str, Any]]]) -> None:
    """One resync pass over the tenants named, each as itself, as the worker runs it."""

    async def tenants() -> list[str]:
        return list(keys)

    await resync_all(engine, Platform(keys), tenants)


async def ids(engine: AsyncEngine, tenant: str, **params: Any) -> tuple[list[str], int]:
    with tenant_scope(tenant):
        listed = await ChannelList(engine).page(("team_ops",), ListParams(**params))
    return [r.id for r in listed.rows], listed.page["pagination"]["total"]


async def test_a_keys_threads_count_in_its_tenant_only(engine: AsyncEngine) -> None:
    kid = f"key_{uuid4().hex[:10]}"
    now = datetime.now(UTC)
    at = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    ours, theirs = f"t-{uuid4().hex[:6]}", f"t-{uuid4().hex[:6]}"
    for tenant in (ours, ours, theirs):
        with tenant_scope(tenant):
            meta: Json = {"ownerEmail": "case-system@harborpine.example", "startedBy": f"key:{kid}"}
            await GraphStore(engine).create_thread(f"gth_{uuid4().hex[:10]}", "agent:ag_x", meta, "team_ops", at)
    await resync(engine, {ours: [summary(kid)]})
    with tenant_scope(ours):
        [row] = await ChannelList(engine).rows(("team_ops",), now=now, ids=[kid])
    assert (row.counts.traffic24h, row.counts.activity7d) == (2, 2), row.counts


async def test_a_resync_follows_its_tenants_keys_and_leaves_the_others(engine: AsyncEngine) -> None:
    ours, theirs = f"t-{uuid4().hex[:6]}", f"t-{uuid4().hex[:6]}"
    kept, revoked, gone = (f"key_{uuid4().hex[:10]}" for _ in range(3))
    await resync(
        engine, {theirs: [summary(kept, name="Theirs")], ours: [summary(kept), summary(revoked), summary(gone)]}
    )
    assert (await ids(engine, ours))[1] == 3
    # platform now lists one key revoked and no longer lists another.
    await resync(engine, {ours: [summary(kept, name="CI renamed"), summary(revoked, status="revoked")]})
    assert await ids(engine, ours) == ([kept], 1)
    with tenant_scope(ours):
        [row] = await ChannelList(engine).rows(("team_ops",), ids=[kept])
    assert row.name == "CI renamed"
    assert await ids(engine, theirs) == ([kept], 1), "one tenant's resync buried or changed another tenant's row"


async def test_equal_names_page_by_type_and_id_without_repeats(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:6]}"
    keys = sorted(f"key_{uuid4().hex[:10]}" for _ in range(3))
    other = f"t-{uuid4().hex[:6]}"
    await resync(engine, {tenant: [summary(k, name="Same") for k in keys], other: [summary(keys[0], name="Same")]})
    with tenant_scope(tenant):
        await MailboxStore(engine).create(
            MailboxRow(
                id=f"mbx_{uuid4().hex[:8]}",
                team_id="team_ops",
                name="Same",
                address=f"{uuid4().hex[:8]}@bank.example",
                provider="imap",
                created_by="b",
                created_at="n",
                updated_at="n",
            )
        )
    first, total = await ids(engine, tenant, page=1, page_size=2)
    second, _ = await ids(engine, tenant, page=2, page_size=2)
    past_end, _ = await ids(engine, tenant, page=9, page_size=2)
    assert total == 4 and first[0].startswith("mbx_") and first[1:] + second == keys, (first, second)
    assert past_end == second, "a page past the end answers the last page"
