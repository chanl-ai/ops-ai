"""Reading the audit log (I7): admins only, their team's entries, or every entry in the tenant when the team's scope
is `all` (the platform team). Entries are written by each store in the transaction of the write they record."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

from .store.audit import AuditLog
from .store.members import Actor, TeamStore
from .teams import Members


def shown(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "teamId": row["team_id"],
        "actor": row["actor"],
        "action": row["action"],
        "targetKind": row["target_kind"],
        "targetId": row["target_id"],
        "requestId": row["request_id"],
        "at": row["at"],
        "detail": row["detail"],
    }


@dataclass
class AuditReader:
    log: AuditLog
    teams: TeamStore
    members: Members

    async def page(self, actor: Actor, filters: dict[str, str | None], page: int, size: int) -> dict[str, Any]:
        await self.members.require_admin(actor)
        everyone = await self.teams.scope_of(actor.tenant_id, actor.team_id) == "all"
        rows, total = await self.log.page(
            actor.tenant_id, None if everyone else actor.team_id, filters=filters, page=page, size=size
        )
        pages = max(1, ceil(total / size))
        return {
            "data": [shown(r) for r in rows],
            "pagination": {
                "page": page,
                "pageSize": size,
                "total": total,
                "totalPages": pages,
                "hasNext": page < pages,
                "hasPrev": page > 1,
            },
            "facets": {},
        }
