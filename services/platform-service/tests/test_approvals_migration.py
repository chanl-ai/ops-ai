"""Migration 0046 changes no one's access, by failure mode: a person of any seeded role, or a Security admin, losing or
gaining a cell when the grid gains the `approvals` area; a team's admin left without `approvals.manage`, so they could
no longer set the team's approval rule they set before; a Builder handed it; and a built-in role an admin had edited
to change settings losing the approval rules it could change. Runs the real chain on the test database: down to
0045, a workspace as it stood there (its roles' cells less the new area), up to head, every person's cells compared
per team. Synchronous: Alembic's environment runs its own event loop."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from ops_access import BUILTIN_ROLES, Assignment, Grant, builtin_roles_for, effective
from ops_service_kit.ids import new_id, now_iso

from .conftest import alembic_config

NOW = "2026-11-20T00:00:00.000Z"
NAMES = {r.id: r.name for r in BUILTIN_ROLES}
MEMBERSHIPS = ("admin", "builder", "approver", "viewer", "chat_user")


async def _run(url: str, statements: list[tuple[str, dict[str, Any]]]) -> list[list[Any]]:
    engine = create_async_engine(url)
    out: list[list[Any]] = []
    async with engine.begin() as c:
        for sql, params in statements:
            result = await c.execute(sa.text(sql), params)
            out.append(list(result.all()) if result.returns_rows else [])
    await engine.dispose()
    return out


def _cells(url: str, tenant: str, user: str, teams: list[str]) -> dict[str, set[tuple[str, str, str]]]:
    """What the person may do in each team, from the stored assignments and cells, as the token is built."""
    held, grid = asyncio.run(
        _run(
            url,
            [
                (
                    "SELECT role_id, team_id FROM role_assignments WHERE tenant_id = :t AND subject_id = :u",
                    {"t": tenant, "u": user},
                ),
                ("SELECT role_id, area, action, scope FROM role_permissions WHERE tenant_id = :t", {"t": tenant}),
            ],
        )
    )
    grids: dict[str, list[Grant]] = {}
    for role, area, action, scope in grid:
        grids.setdefault(role, []).append((area, action, scope))
    assignments = [Assignment(r, NAMES.get(r) or r, team, "person") for r, team in held]
    per_team = effective(assignments, grids, teams, NOW)
    return {t: {(a, x, g.scope) for (a, x), g in per_team.get(t, {}).items()} for t in teams}


def test_no_one_gains_or_loses_access_and_team_admins_keep_their_approval_rules(database_url: str) -> None:
    tenant, ops, security = new_id("ten"), new_id("team"), new_id("team")
    people = {role: new_id("usr") for role in MEMBERSHIPS}
    now = now_iso()
    command.downgrade(alembic_config(), "0045_api_key_revision")
    try:
        writes: list[tuple[str, dict[str, Any]]] = [
            (
                "INSERT INTO tenants (id, name, status, allowed_domains, created_at, security_team_id) "
                "VALUES (:t, :t, 'active', '[]', :now, :sec)",
                {"t": tenant, "now": now, "sec": security},
            )
        ]
        for team in (ops, security):
            writes.append(
                (
                    "INSERT INTO teams (id, tenant_id, name, name_key, owner_groups, scope, created_at) "
                    "VALUES (:id, :t, :id, :id, '[]', 'owned', :now)",
                    {"id": team, "t": tenant, "now": now},
                )
            )
        # The workspace's roles as 0045 left them: the seed less the area 0046 adds, and a Reviewer an admin had edited
        # to change the workspace's settings.
        for role in BUILTIN_ROLES:
            writes.append(
                (
                    "INSERT INTO roles (tenant_id, id, name, builtin, description, created_at) "
                    "VALUES (:t, :id, :n, true, '', :now)",
                    {"t": tenant, "id": role.id, "n": role.name, "now": now},
                )
            )
            cells = [g for g in role.grants if g[0] != "approvals"]
            if role.id == "reviewer":
                cells.append(("settings", "manage", "all"))
            for area, action, scope in cells:
                writes.append(
                    (
                        "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
                        "VALUES (:t, :r, :a, :x, :s)",
                        {"t": tenant, "r": role.id, "a": area, "x": action, "s": scope},
                    )
                )
        for member, user in people.items():
            writes.append(
                (
                    "INSERT INTO users (id, tenant_id, email, name, status, created_at) "
                    "VALUES (:u, :t, :e, 'P', 'active', :now)",
                    {"u": user, "t": tenant, "e": f"{user}@bank.test", "now": now},
                )
            )
            for team in (ops, security):
                for role in builtin_roles_for(member, security_team=team == security):
                    writes.append(
                        (
                            "INSERT INTO role_assignments (id, tenant_id, subject_kind, subject_id, role_id, team_id, "
                            "granted_by, reason, source, created_at) "
                            "VALUES (:id, :t, 'person', :u, :r, :team, 'test', 'test', 'membership', :now)",
                            {"id": new_id("ras"), "t": tenant, "u": user, "r": role, "team": team, "now": now},
                        )
                    )
        asyncio.run(_run(database_url, writes))
        before = {m: _cells(database_url, tenant, u, [ops, security]) for m, u in people.items()}
    finally:
        command.upgrade(alembic_config(), "head")
    after = {m: _cells(database_url, tenant, u, [ops, security]) for m, u in people.items()}

    def approvals(cells: set[tuple[str, str, str]]) -> set[str]:
        return {x for a, x, _ in cells if a == "approvals"}

    for member in MEMBERSHIPS:
        for team in (ops, security):
            assert {c for c in after[member][team] if c[0] != "approvals"} == before[member][team], (member, team)
            assert before[member][team] and not approvals(before[member][team]), (member, team)
    for team in (ops, security):
        assert "manage" in approvals(after["admin"][team]), team
        assert approvals(after["builder"][team]) == {"view"}, team
        assert approvals(after["viewer"][team]) == {"view"}, team
        assert approvals(after["chat_user"][team]) == set(), team
        # The edited Reviewer changed settings, so it keeps the team's approval rules.
        assert approvals(after["approver"][team]) == {"view", "manage"}, team
    # Run again (down one, up) it adds nothing twice and changes nobody.
    command.downgrade(alembic_config(), "0045_api_key_revision")
    command.upgrade(alembic_config(), "head")
    assert {m: _cells(database_url, tenant, u, [ops, security]) for m, u in people.items()} == after


def test_a_rollback_leaves_self_approval_on_only_where_the_workspace_had_it_on(database_url: str) -> None:
    # The code before 0046 reads any stored object as on, so a per-team value must reach it as one boolean.
    now, team = now_iso(), new_id("team")
    stored = {new_id("ten"): ({"*": False, team: True}, False), new_id("ten"): ({"*": True, team: False}, True)}
    writes: list[tuple[str, dict[str, Any]]] = []
    for tenant, (value, _) in stored.items():
        writes.append(
            (
                "INSERT INTO tenants (id, name, status, allowed_domains, created_at) "
                "VALUES (:t, :t, 'active', '[]', :now)",
                {"t": tenant, "now": now},
            )
        )
        writes.append(
            (
                "INSERT INTO policies (tenant_id, key, value, updated_by, updated_at) "
                "VALUES (:t, 'requesterMayDecide', :v, 'test', :now)",
                {"t": tenant, "v": json.dumps(value), "now": now},
            )
        )
    asyncio.run(_run(database_url, writes))
    command.downgrade(alembic_config(), "0045_api_key_revision")
    try:
        for tenant, (_, after) in stored.items():
            [rows] = asyncio.run(
                _run(
                    database_url,
                    [("SELECT value FROM policies WHERE tenant_id = :t AND key = 'requesterMayDecide'", {"t": tenant})],
                )
            )
            value = rows[0][0]
            assert (json.loads(value) if isinstance(value, str) else value) is after, tenant
    finally:
        command.upgrade(alembic_config(), "head")
