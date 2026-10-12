"""Writes the development seed. Each row is inserted only when absent, so a second run changes nothing and a seeded
person's later edits survive a restart. Runs as the seed's own tenant, so row-level security checks every row."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert

from ops_service_kit.ids import now_iso

from .tables import members, teams, tenants, users
from .tenancy import TenantDb


async def write_seed(db: TenantDb, data: dict[str, Any]) -> None:
    tenant = data["tenant"]
    tenant_id = str(tenant["id"])
    now = now_iso()
    async with db.tenant_tx(tenant_id) as c:
        await c.execute(
            insert(tenants)
            .values(
                id=tenant_id,
                name=tenant["name"],
                status="active",
                allowed_domains=tenant["allowedDomains"],
                created_at=now,
            )
            .on_conflict_do_nothing()
        )
        for team in data["teams"]:
            await c.execute(
                insert(teams)
                .values(
                    id=team["id"],
                    tenant_id=tenant_id,
                    name=team["name"],
                    owner_groups=team["ownerGroups"],
                    scope=team["scope"],
                    created_at=now,
                )
                .on_conflict_do_nothing()
            )
        for person in data["people"]:
            await c.execute(
                insert(users)
                .values(
                    id=person["id"],
                    tenant_id=tenant_id,
                    email=person["email"],
                    name=person["name"],
                    status="active",
                    created_at=now,
                )
                .on_conflict_do_nothing()
            )
            for team_id, role in person["teams"].items():
                await c.execute(
                    insert(members)
                    .values(
                        id=f"mem_{person['id']}_{team_id}",
                        tenant_id=tenant_id,
                        team_id=team_id,
                        user_id=person["id"],
                        email=person["email"],
                        role=role,
                        status="active",
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing()
                )
