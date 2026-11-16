"""Writes the development seed, create-only: a row the file names that is absent is inserted, and a row that exists is
left as it is, so a name, a role or a team a person changed through the API survives every restart. The built-in roles
are added when missing, and a membership the seed creates gets its role assignments; a person's `everyTeam` roles (an id
or a list) are assigned in every team (`*`) when missing, and `admin` there makes a workspace admin. Runs as the seed's
own tenant, so row-level security checks every row.

A seeded id held by another tenant cannot be moved from here (row-level security hides it, and the composite foreign
keys tie its sessions, keys and audit to that tenant), so the seed stops and says to reset the dev database instead
of starting with people who sign in to the wrong tenant.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_access import ANY_TEAM
from ops_access.platform_events import TEAM_CREATED
from ops_service_kit.ids import now_iso
from ops_store.dialect import insert_ignore, upsert
from ops_store.outbox import add as add_event
from ops_store.store import Store

from .policies import write_new_workspace_policies
from .roles import bump_version, ensure_builtin_roles, ensure_owner, mirror_membership
from .tables import members, platform_outbox, role_assignments, teams, tenants, users
from .tenancy import SEED_ID_CHECK, TenantDb

# One assignment per subject, role and team (uq_role_assignments): a seed run again adds none.
GRANT_KEY = ["tenant_id", "subject_kind", "subject_id", "role_id", "team_id"]


class SeedConflictError(RuntimeError):
    """A seeded id belongs to another tenant."""


async def _visible(c: AsyncConnection, table: sa.Table, ids: list[str]) -> set[str]:
    return {str(i) for i in (await c.execute(sa.select(table.c.id).where(table.c.id.in_(ids)))).scalars()}


async def write_seed(
    db: TenantDb, data: dict[str, Any], *, security_team: str = "team_security", everyone_admin: bool = False
) -> None:
    """`everyone_admin` (dev only, OPS_SEED_EVERYONE_ADMIN) adds Admin in every team to each person's own roles. Like
    every seeded row it is only ever added: turning it off later leaves what it gave; the API takes it away."""
    tenant = data["tenant"]
    tenant_id = str(tenant["id"])
    now = now_iso()
    async with db.tenant_tx(tenant_id) as c:
        first = {
            "id": tenant_id,
            "name": tenant["name"],
            "status": "active",
            "allowed_domains": tenant["allowedDomains"],
            "created_at": now,
        }
        made_tenant = await c.execute(insert_ignore(c, tenants, first, keys=["id"]))
        seeded: list[dict[str, Any]] = data.get("teams") or []
        if made_tenant.rowcount == 1:
            await write_new_workspace_policies(c, tenant_id, at=now)
        if security_team in {str(t["id"]) for t in seeded}:
            # The workspace's record names its Security team; a workspace that already names one keeps it.
            await c.execute(
                tenants.update()
                .where(tenants.c.id == tenant_id, tenants.c.security_team_id.is_(None))
                .values(security_team_id=security_team)
            )
        # Before any upsert: an id another tenant holds conflicts invisibly, and the error would not say which.
        held = [
            (table.name, i)
            for table, ids in (
                (teams, [str(t["id"]) for t in data["teams"]]),
                (users, [str(p["id"]) for p in data["people"]]),
            )
            if (missing := set(ids) - await _visible(c, table, ids))
            for i in sorted(missing)
            if await _taken(db, table, i)
        ]
        if held:
            names = ", ".join(f"{t} {i}" for t, i in held)
            raise SeedConflictError(
                f"seed: {names} already exist under another tenant than {tenant_id}; rebuild the dev database "
                "(make up without KEEP_DATA=1, or make db-reset) and start again"
            )
        await ensure_builtin_roles(c, tenant_id, at=now)
        for team in data["teams"]:
            fields = {
                "name": team["name"],
                "name_key": str(team["name"]).lower(),
                "owner_groups": team["ownerGroups"],
                "scope": team["scope"],
            }
            row = {"id": team["id"], "tenant_id": tenant_id, "created_at": now, **fields}
            made = await c.execute(insert_ignore(c, teams, row, keys=["id"]))
            if made.rowcount:
                # A seeded team, the install's first team included, gets each service's defaults like any new team;
                # a team already there reports nothing again.
                await add_event(
                    c, platform_outbox, tenant_id=tenant_id, team_id=str(team["id"]), name=TEAM_CREATED,
                    key=str(team["id"]), payload={}, actor="seed",
                )  # fmt: skip
        for person in data["people"]:
            fields = {"email": person["email"], "name": person["name"], "status": "active"}
            # A seeded person's address and name belong to the seed file (no route changes them), so a database seeded
            # before the file changed them signs in with the new ones; their roles and status stay as people set them.
            row = {"id": person["id"], "tenant_id": tenant_id, "created_at": now, **fields}
            await c.execute(upsert(c, users, row, keys=["id"], update=["email", "name"]))
            await c.execute(sa.update(members).where(members.c.user_id == person["id"]).values(email=person["email"]))
            for team_id, role in person["teams"].items():
                fields = {"email": person["email"], "role": role, "status": "active", "updated_at": now}
                row = {
                    "id": f"mem_{person['id']}_{team_id}",
                    "tenant_id": tenant_id,
                    "team_id": team_id,
                    "user_id": person["id"],
                    "created_at": now,
                    **fields,
                }
                created = await c.execute(insert_ignore(c, members, row, keys=["id"]))
                if created.rowcount != 1:
                    continue
                await mirror_membership(
                    c,
                    tenant_id=tenant_id,
                    team_id=team_id,
                    user_id=person["id"],
                    member_role=role,
                    security_team=security_team,
                    granted_by="seed",
                    at=now,
                )
            named: list[str] = (
                [person["everyTeam"]] if isinstance(person.get("everyTeam"), str) else person.get("everyTeam") or []
            )
            every = [*named, *(["admin"] if everyone_admin and "admin" not in named else [])]
            for role_id in every:
                # A workspace role: the built-in role in every team (`*`); Admin there makes a workspace admin,
                # Security admin there holds the Security team's actions wherever that team is.
                grant = {
                    "id": f"ras_{person['id']}_every_{role_id}",
                    "tenant_id": tenant_id,
                    "subject_kind": "person",
                    "subject_id": person["id"],
                    "role_id": role_id,
                    "team_id": ANY_TEAM,
                    "granted_by": "seed",
                    "reason": "Seeded workspace role",
                    "source": "grant",
                    "created_at": now,
                }
                await c.execute(insert_ignore(c, role_assignments, grant, keys=GRANT_KEY))
            if every:
                await bump_version(c, tenant_id)
        await ensure_owner(c, tenant_id, at=now)


async def _taken(db: TenantDb, table: sa.Table, row_id: str) -> bool:
    """Whether any tenant holds `row_id`: the primary key is global, so an insert of it under no tenant's eyes fails.
    Read as the login with no role set (a base `Store`'s system role is none): the dev seed connects as the compose
    superuser, which row-level security does not filter. A login that cannot read the table answers not taken."""
    try:
        async with Store(db.engine).system_tx(SEED_ID_CHECK) as c, db.attempt(c):
            found = await c.execute(sa.select(sa.func.count()).select_from(table).where(table.c.id == row_id))
            return found.scalar_one() > 0
    except DBAPIError:
        return False
