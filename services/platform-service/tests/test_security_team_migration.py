"""Migration 0029 keeps each workspace's Security team once no setting stands in for it, by failure mode: a workspace
that relied on the install default left with none, one without that team given it, and one that named its own
overwritten. Runs the real chain on the test database: down to 0028, three workspaces written as the superuser, up to
head."""

from __future__ import annotations

import asyncio

from alembic import command

from ops_service_kit.ids import new_id, now_iso

from .conftest import alembic_config
from .test_role_migration import _rows, _run  # pyright: ignore[reportPrivateUsage]


def test_each_workspace_keeps_the_security_team_it_had(database_url: str) -> None:
    without, own = new_id("ten"), new_id("ten")
    risk = new_id("team")
    now = now_iso()
    # A team id is unique in the database, so the workspace holding `team_security` is the one that relied on it.
    found = asyncio.run(_rows(database_url, "SELECT tenant_id FROM teams WHERE id = 'team_security'", {}))
    relied = str(found[0][0]) if found else new_id("ten")
    command.downgrade(alembic_config(), "0028_builder_every_team_cell")
    try:
        tenant = "INSERT INTO tenants (id, name, status, allowed_domains, created_at, security_team_id) "
        team = "INSERT INTO teams (id, tenant_id, name, name_key, owner_groups, scope, created_at) "
        writes = [
            (tenant + "VALUES (:t, :t, 'active', '[]', :now, NULL)", {"t": without, "now": now}),
            (tenant + "VALUES (:t, :t, 'active', '[]', :now, :team)", {"t": own, "now": now, "team": risk}),
            (team + "VALUES (:id, :t, 'Risk', 'risk', '[]', 'owned', :now)", {"id": risk, "t": own, "now": now}),
        ]
        if found:
            writes.append(("UPDATE tenants SET security_team_id = NULL WHERE id = :t", {"t": relied}))
        else:
            writes += [
                (tenant + "VALUES (:t, :t, 'active', '[]', :now, NULL)", {"t": relied, "now": now}),
                (
                    team + "VALUES ('team_security', :t, 'Security', 'security', '[]', 'owned', :now)",
                    {"t": relied, "now": now},
                ),
            ]
        asyncio.run(_run(database_url, writes))
    finally:
        command.upgrade(alembic_config(), "head")
    rows = asyncio.run(
        _rows(
            database_url,
            "SELECT id, security_team_id FROM tenants WHERE id IN (:a, :b, :c)",
            {"a": relied, "b": without, "c": own},
        )
    )
    assert dict(rows) == {relied: "team_security", without: None, own: risk}
