"""Migration 0055 (c-214) drops agents-service's old publish-policy tables, by failure mode: it writes into
platform-service's `policies` (an agents migration may touch agents tables only), so a value a team admin set
through /v1/policies is overwritten; the downgrade leaves tables 0038's downgrade cannot drop."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.ids import new_id, now_iso

ROOT = Path(__file__).resolve().parents[2]
BEFORE = "0054_drop_mailbox_deployments"


async def _sql(url: str, *statements: tuple[str, dict[str, Any]]) -> list[Any]:
    engine = create_async_engine(url)
    out: list[Any] = []
    async with engine.begin() as c:
        for text, params in statements:
            r = await c.execute(sa.text(text), params)
            out.append(r.all() if r.returns_rows else None)
    await engine.dispose()
    return out


def test_the_old_tables_go_and_platforms_policies_are_untouched(database_url: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)
    old, newer = new_id("ten"), new_id("ten")
    saved = {"team_ops": {"agents": "never"}}
    tenant = "INSERT INTO tenants (id, name, status, allowed_domains, created_at) VALUES (:t, :t, 'active', '[]', :at)"
    document = (
        "INSERT INTO publish_policies (tenant_id, version, document, updated_by, updated_at) "
        "VALUES (:t, 3, :d, 'priya@bank.test', :at)"
    )
    at = now_iso()
    asyncio.run(
        _sql(
            database_url,
            (tenant, {"t": old, "at": at}),
            (tenant, {"t": newer, "at": at}),
            (document, {"t": old, "d": json.dumps(saved), "at": at}),
            (document, {"t": newer, "d": json.dumps({"team_ops": {"agents": "always"}}), "at": at}),
            (
                "INSERT INTO policies (tenant_id, key, value, updated_by, updated_at) "
                "VALUES (:t, 'publishReview', CAST(:v AS json), 'usr_admin', :at)",
                {"t": newer, "v": json.dumps({"team_ops": {"agents": "major"}}), "at": at},
            ),
        )
    )
    command.upgrade(cfg, "head")
    (rows, tables) = asyncio.run(
        _sql(
            database_url,
            (
                "SELECT tenant_id, value FROM policies WHERE key = 'publishReview' AND tenant_id IN (:a, :b)",
                {"a": old, "b": newer},
            ),
            ("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'publish_polic%'", {}),
        )
    )
    values = {r[0]: r[1] for r in rows}
    assert old not in values, "nothing is copied into another service's table"
    assert values[newer] == {"team_ops": {"agents": "major"}}, "a value set through /v1/policies is kept"
    assert tables == []
    command.downgrade(cfg, BEFORE)
    command.upgrade(cfg, "head")
    asyncio.run(
        _sql(
            database_url,
            ("DELETE FROM policies WHERE tenant_id IN (:a, :b)", {"a": old, "b": newer}),
            ("DELETE FROM tenants WHERE id IN (:a, :b)", {"a": old, "b": newer}),
        )
    )
