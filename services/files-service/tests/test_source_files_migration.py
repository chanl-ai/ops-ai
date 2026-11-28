"""The source files migration fills every tenant's files and versions when it runs as a login that owns the tables but
is no superuser and has no BYPASSRLS, as a deployment's migrator is: with FORCE on, PostgreSQL refuses a statement
that row security would change for that owner, so a fill that only switched row security off stopped the upgrade half
way. Synchronous: Alembic's environment runs its own event loop."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.ids import new_id

ALEMBIC_INI = str(Path(__file__).resolve().parents[1] / "alembic.ini")
BEFORE = "files_0017"
REVISION = "20261123_2345_source_files"
OWNED = ("files", "file_versions")
T0 = datetime(2026, 1, 1, tzinfo=UTC)
FILE = (
    "INSERT INTO files (id, tenant_id, team, name, mime, size, purpose, status, scan_status, sensitivity, "
    "sensitivity_suggested, retention_class_id, immutable, storage_backend, storage_container, storage_key, "
    "declared_size, uploaded_by, uploaded_at, version_count) VALUES (:id, :t, 'team_a', 'a.pdf', 'application/pdf', 1, "
    "'general', 'available', :scan, 'internal', false, 'standard', false, 'local', 'c', :id, 1, 'a@x', :at, 1)"
)
VERSION = (
    "INSERT INTO file_versions (file_id, version, tenant_id, team, digest, size, storage_key, uploaded_by, "
    "uploaded_at, current) VALUES (:id, 1, :t, 'team_a', :id, 1, :id, 'a@x', :at, true)"
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
def test_files_and_versions_of_two_tenants_are_filled_by_a_migrator_that_only_owns_them(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = Config(ALEMBIC_INI)
    url = sa.engine.make_url(database_url)
    role = f"ops_migrator_{new_id('r')[2:10].lower()}"
    rows = {new_id("fil"): (new_id("ten"), "clean"), new_id("fil"): (new_id("ten"), "pending")}
    ids = list(rows)
    pick = {"a": ids[0], "b": ids[1]}
    command.downgrade(cfg, BEFORE)
    seed = [(s, {"id": f, "t": t, "scan": scan, "at": T0}) for f, (t, scan) in rows.items() for s in (FILE, VERSION)]
    asyncio.run(
        _run(
            database_url,
            [
                *seed,
                (f"CREATE ROLE {role} LOGIN PASSWORD 'pw' NOBYPASSRLS NOSUPERUSER", {}),
                (f"GRANT USAGE, CREATE ON SCHEMA public TO {role}", {}),
                (f"GRANT SELECT, UPDATE ON alembic_version_files TO {role}", {}),
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
        files, versions, forced = asyncio.run(
            _run(
                database_url,
                [
                    (
                        "SELECT id, source_scope, source_key_hash FROM files WHERE id IN (:a, :b)",
                        pick,
                    ),
                    (
                        "SELECT file_id, scan_status FROM file_versions WHERE file_id IN (:a, :b)",
                        pick,
                    ),
                    (
                        "SELECT relname, relforcerowsecurity FROM pg_class WHERE relname IN ('files', 'file_versions')",
                        {},
                    ),
                ],
            )
        )
        assert sorted(files) == sorted((f, "upload", f) for f in ids)
        assert sorted(versions) == sorted((f, scan) for f, (_t, scan) in rows.items())
        assert sorted(forced) == [("file_versions", True), ("files", True)]
    finally:
        monkeypatch.undo()
        asyncio.run(
            _run(
                database_url,
                [
                    *((f"ALTER TABLE {t} OWNER TO {url.username}", {}) for t in OWNED),
                    (f"REVOKE ALL ON alembic_version_files FROM {role}", {}),
                    (f"REVOKE ALL ON SCHEMA public FROM {role}", {}),
                    (f"DROP ROLE {role}", {}),
                    ("DELETE FROM file_versions WHERE file_id IN (:a, :b)", pick),
                    ("DELETE FROM files WHERE id IN (:a, :b)", pick),
                ],
            )
        )
        command.upgrade(cfg, "head")
