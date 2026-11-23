"""A person who collected several subjects at one provider before `uq_signin_identities_person` keeps only the oldest
link through the upgrade; other people's links stay. Synchronous: Alembic's environment runs its own event loop."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.ids import new_id

from .conftest import alembic_config

BEFORE = "20261122_2022_list_sort_indexes"


async def _seed(url: str, tenant: str, ana: str, bo: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as c:
        await c.execute(
            sa.text(
                "INSERT INTO tenants (id, name, status, allowed_domains, created_at)"
                " VALUES (:t, :t, 'active', '[]', '2026-01-01T00:00:00.000Z')"
            ),
            {"t": tenant},
        )
        await c.execute(
            sa.text(
                "INSERT INTO signin_providers (id, tenant_id, kind, label, enabled, config, created_at, updated_at)"
                " VALUES ('sip_m', :t, 'oidc', 'Bank', true, '{}', '2026-01-01T00:00:00.000Z',"
                " '2026-01-01T00:00:00.000Z')"
            ),
            {"t": tenant},
        )
        for user in (ana, bo):
            await c.execute(
                sa.text(
                    "INSERT INTO users (id, tenant_id, email, name, status, created_at)"
                    " VALUES (:u, :t, :u, :u, 'active', '2026-01-01T00:00:00.000Z')"
                ),
                {"u": user, "t": tenant},
            )
        for sid, user, subject, at in (
            ("sid_later", ana, "second-account", "2026-03-01T00:00:00.000Z"),
            ("sid_first", ana, "own-account", "2026-02-01T00:00:00.000Z"),
            ("sid_bo", bo, "bo-account", "2026-03-01T00:00:00.000Z"),
        ):
            await c.execute(
                sa.text(
                    "INSERT INTO signin_identities (id, tenant_id, provider_id, subject, user_id, created_at,"
                    " last_used_at) VALUES (:i, :t, 'sip_m', :s, :u, :a, '2026-04-01T00:00:00.000Z')"
                ),
                {"i": f"{sid}_{tenant}", "t": tenant, "s": subject, "u": user, "a": at},
            )
    await engine.dispose()


async def _links(url: str, tenant: str) -> list[tuple[str, str]]:
    engine = create_async_engine(url)
    async with engine.connect() as c:
        q = sa.text("SELECT user_id, subject FROM signin_identities WHERE tenant_id = :t ORDER BY user_id, subject")
        found = [(str(r[0]), str(r[1])) for r in (await c.execute(q, {"t": tenant})).all()]
    await engine.dispose()
    return found


@pytest.mark.postgresql_only("SQL Server's scratch database holds the golden DDL, not the chain")
def test_a_person_with_two_subjects_at_one_provider_keeps_the_oldest(database_url: str) -> None:
    tenant, ana, bo = new_id("ten"), new_id("usr"), new_id("usr")
    command.downgrade(alembic_config(), BEFORE)
    try:
        asyncio.run(_seed(database_url, tenant, ana, bo))
        command.upgrade(alembic_config(), "head")
        assert asyncio.run(_links(database_url, tenant)) == sorted([(ana, "own-account"), (bo, "bo-account")])
    finally:
        command.upgrade(alembic_config(), "head")
