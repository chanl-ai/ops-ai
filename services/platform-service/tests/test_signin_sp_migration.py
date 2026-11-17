"""A database that ran 0034 before its released text holds platform_signin_sp's first body (`->>`); the chain brings it
to the released body, a re-run keeps it, the way down leaves the body 0034 leaves, and the function still answers.
Synchronous: Alembic's environment runs its own event loop."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from .conftest import alembic_config

BEFORE = "0043_roles_by_builtin"
FIRST_BODY = (
    "SELECT p.tenant_id, p.id, p.kind, p.enabled, COALESCE((p.config->>'tiles')::boolean, true) "
    "FROM public.signin_providers p WHERE p.sp_id = p_sp_id"
)
RETURNS = "RETURNS TABLE (tenant_id varchar, provider_id varchar, kind varchar, enabled boolean, tiles boolean)"


async def _body(url: str, *, set_first: bool = False) -> str:
    engine = create_async_engine(url)
    async with engine.begin() as c:
        if set_first:
            await c.execute(
                sa.text(
                    f"CREATE OR REPLACE FUNCTION platform_signin_sp(p_sp_id text) {RETURNS} AS $$ {FIRST_BODY} $$ "
                    "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp"
                )
            )
        body = (await c.execute(sa.text("SELECT prosrc FROM pg_proc WHERE proname = 'platform_signin_sp'"))).scalar()
        await c.execute(sa.text("SELECT * FROM platform_signin_sp('no-such-sp')"))
    await engine.dispose()
    return str(body)


@pytest.mark.postgresql_only("SQL Server's function never held the first body")
def test_an_early_signin_sp_body_is_brought_to_the_released_one(database_url: str) -> None:
    command.downgrade(alembic_config(), BEFORE)
    try:
        assert "->>" in asyncio.run(_body(database_url, set_first=True))
        command.upgrade(alembic_config(), "head")
        released = asyncio.run(_body(database_url))
        assert "json_extract_path_text(p.config, 'tiles')" in released and "->>" not in released
        command.downgrade(alembic_config(), BEFORE)
        assert asyncio.run(_body(database_url)) == released
        command.upgrade(alembic_config(), "head")
        assert asyncio.run(_body(database_url)) == released
    finally:
        command.upgrade(alembic_config(), "head")
