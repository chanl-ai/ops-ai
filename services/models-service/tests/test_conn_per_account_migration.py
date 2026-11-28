"""Migration 20261128_0015 gives model connections and aliases an account and the tenant policy. It deletes the
install-wide rows rather than guess an account for them, so an admin re-picks them. It runs as a deployment's
migrator does: a login that owns the tables but is no superuser and has no BYPASSRLS, so with FORCE on PostgreSQL
refuses any statement row security would change for it. Synchronous: Alembic's environment runs its own event loop."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.ids import new_id

ALEMBIC_INI = str(Path(__file__).resolve().parents[1] / "alembic.ini")
BEFORE = "20261122_2017_list_sort_indexes"
REVISION = "20261128_0015_conn_per_account"
OWNED = ("provider_connections", "model_aliases")
CONNECTION = (
    "INSERT INTO provider_connections (id, name, type, base_url, created_at) "
    "VALUES (:id, :id, 'openai-compatible', 'https://api.openai.com/v1', '2026-01-01T00:00:00Z')"
)
ALIAS = (
    "INSERT INTO model_aliases (name, version, kind, provider_id, model_id, cleared_sensitivity, input_per_million, "
    "output_per_million, status, created_at) VALUES (:name, 1, 'chat', :id, 'gpt-5.2', 'internal', 1, 2, 'current', "
    "'2026-01-01T00:00:00Z')"
)


async def _run(url: str, statements: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    engine = create_async_engine(url)
    out: list[Any] = []
    async with engine.begin() as c:
        for sql, params in statements:
            result = await c.execute(sa.text(sql), params)
            out.append(result.all() if result.returns_rows else None)
    await engine.dispose()
    return out


@pytest.mark.postgresql_only("SQL Server's scratch database holds the golden DDL, not the chain")
def test_install_wide_connections_and_aliases_are_cleared_by_a_migrator_that_only_owns_them(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = Config(ALEMBIC_INI)
    url = sa.engine.make_url(database_url)
    role = f"ops_migrator_{new_id('r')[2:10].lower()}"
    conn, alias = new_id("prov"), f"walk-{new_id('a')[2:8].lower()}"
    command.downgrade(cfg, BEFORE)
    asyncio.run(
        _run(
            database_url,
            [
                (CONNECTION, {"id": conn}),
                (ALIAS, {"name": alias, "id": conn}),
                (f"CREATE ROLE {role} LOGIN PASSWORD 'pw' NOBYPASSRLS NOSUPERUSER", {}),
                (f"GRANT USAGE, CREATE ON SCHEMA public TO {role}", {}),
                (f"GRANT SELECT, UPDATE ON alembic_version_models TO {role}", {}),
                *((f"ALTER TABLE {t} OWNER TO {role}", {}) for t in OWNED),
            ],
        )
    )
    try:
        monkeypatch.setenv(
            "OPS_DATABASE_URL", url.set(username=role, password="pw").render_as_string(hide_password=False)
        )
        command.upgrade(cfg, REVISION)
        monkeypatch.undo()
        conns, aliases, forced, policies = asyncio.run(
            _run(
                database_url,
                [
                    ("SELECT count(*) FROM provider_connections", {}),
                    ("SELECT count(*) FROM model_aliases", {}),
                    (
                        "SELECT relname, relforcerowsecurity FROM pg_class "
                        "WHERE relname IN ('provider_connections', 'model_aliases')",
                        {},
                    ),
                    (
                        "SELECT DISTINCT tablename FROM pg_policies "
                        "WHERE tablename IN ('provider_connections', 'model_aliases')",
                        {},
                    ),
                ],
            )
        )
        assert (conns, aliases) == ([(0,)], [(0,)])
        assert sorted(forced) == [("model_aliases", True), ("provider_connections", True)]
        assert sorted(policies) == [("model_aliases",), ("provider_connections",)]
    finally:
        monkeypatch.undo()
        asyncio.run(
            _run(
                database_url,
                [
                    *((f"ALTER TABLE {t} OWNER TO {url.username}", {}) for t in OWNED),
                    (f"REVOKE ALL ON alembic_version_models FROM {role}", {}),
                    (f"REVOKE ALL ON SCHEMA public FROM {role}", {}),
                    (f"DROP ROLE {role}", {}),
                ],
            )
        )
        command.upgrade(cfg, "head")
