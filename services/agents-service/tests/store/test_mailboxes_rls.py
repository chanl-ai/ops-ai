"""Mailbox records on PostgreSQL (c-199), by failure mode: one tenant reads another's mailbox; the role that bypasses
row-level security, kept for the sweeper and timer loops, can read mailboxes. Runs on the migrated test database."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.app import seed_mailboxes
from ops_agents.store.mailboxes import MailboxRow, MailboxStore
from ops_agents.store.tenancy import LOCAL_TENANT, system_tx, tenant_scope
from ops_service_kit.ids import now_iso


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def connect(engine: AsyncEngine, tenant: str) -> MailboxRow:
    now = now_iso()
    m = MailboxRow(
        id=f"mbx_{uuid4().hex[:10]}",
        team_id="team_ops",
        name="Intake",
        address=f"intake-{uuid4().hex[:8]}@bank.example",
        provider="imap",
        created_by="b",
        created_at=now,
        updated_at=now,
    )
    with tenant_scope(tenant):
        await MailboxStore(engine).create(m)
    return m


async def test_a_tenant_reads_only_its_own_mailboxes(engine: AsyncEngine) -> None:
    a, b = f"a-{uuid4().hex[:8]}", f"b-{uuid4().hex[:8]}"
    m = await connect(engine, a)
    store = MailboxStore(engine)
    assert await store.by_address(a, m.address) is not None
    assert await store.by_address(b, m.address) is None
    with tenant_scope(b):
        assert await store.get(m.id) is None
        assert [x.id for x in await store.list(team=None)] == []


async def test_the_bypass_role_cannot_read_mailboxes(engine: AsyncEngine) -> None:
    if engine.dialect.name != "postgresql":
        pytest.skip("row-level security and roles are PostgreSQL's")
    await connect(engine, f"a-{uuid4().hex[:8]}")
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with system_tx(engine) as c:
            await c.execute(sa.text("select count(*) from mailboxes"))


async def test_a_seed_file_that_renames_a_mailbox_replaces_it_and_keeps_peoples_own(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    # A seeded mailbox moved to a new id keeps its address: left in place, the old row clashes with the new one and
    # agents-service fails to start.

    address = f"levy-{uuid4().hex[:8]}@bank.example"
    own = await connect(engine, LOCAL_TENANT)
    seed = tmp_path / "mailboxes.json"
    for mailbox_id in ("mbx_seed_old", "mbx_seed_new"):
        seed.write_text(json.dumps([{"id": mailbox_id, "name": "Levy", "address": address, "provider": "imap"}]))
        await seed_mailboxes(engine, seed)
    store = MailboxStore(engine)
    assert (await store.by_address(LOCAL_TENANT, address) or own).id == "mbx_seed_new"
    assert await store.by_address(LOCAL_TENANT, own.address) is not None
