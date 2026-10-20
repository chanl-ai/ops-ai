"""Reading the audit log (I7): admins only, their team's entries, or every entry in the tenant when the team's scope
is `all` (the platform team). Entries are written by each store in the transaction of the write they record."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

from .store.audit import KIND, VIEWS, AuditLog
from .store.members import Actor, TeamStore
from .teams import Members

# People read reviewer for the stored `approver` (roles-and-permissions, open question 1).
ROLE_LABEL = {"admin": "admin", "builder": "builder", "approver": "reviewer", "viewer": "viewer"}


def words(key: object) -> str:
    """A catalogue key read as words: `api_keys` is "api keys"."""
    return str(key or "").replace("_", " ")


def summary(row: dict[str, Any]) -> str:
    """One line a person reads, from the action and its detail."""
    d: dict[str, Any] = row["detail"] or {}
    target = str(row.get("target_name") or row["target_id"])
    email = str(d.get("email", target))

    def role(key: str) -> str:
        return ROLE_LABEL.get(str(d.get(key)), str(d.get(key)))

    lines = {
        "member.invite": lambda: f"Invited {email} as {role('role')}",
        "member.accept": lambda: f"{email} accepted the invitation and joined",
        "member.role": lambda: f"Changed {target}'s role from {role('from')} to {role('to')}",
        "member.remove": lambda: f"Removed {target}",
        "key.create": lambda: f"Created API key {target}",
        "key.revoke": lambda: f"Revoked API key {target}",
        "auth.sign_in": lambda: "Signed in",
        "auth.sign_out": lambda: "Signed out",
        "auth.step_up": lambda: "Signed in again to confirm a decision",
        "auth.refresh_reuse": lambda: "A reused sign-in token ended every session",
        "team.rename": lambda: f"Renamed the team to {d.get('to', target)}",
        "access.check": lambda: (
            f"Checked {target}'s access to {words(d.get('action'))} on {words(d.get('area'))}: "
            + ("allowed" if d.get("allowed") else "refused")
        ),
    }
    line = lines.get(str(row["action"]))
    return line() if line else str(row["action"])


def shown(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "teamId": row["team_id"],
        "team": row.get("team_name"),
        "actor": row["actor"],
        "actorName": row.get("actor_name"),
        "actorEmail": row.get("actor_email"),
        "action": row["action"],
        "kind": KIND.get(row["action"], "edited"),
        "summary": summary(row),
        "targetKind": row["target_kind"],
        "targetId": row["target_id"],
        "targetName": row.get("target_name"),
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
        await self.members.require_admin(actor, "audit", "view")
        everyone = await self.teams.scope_of(actor.tenant_id, actor.team_id) == "all"
        team = None if everyone else actor.team_id
        rows, total = await self.log.page(actor.tenant_id, team, filters=filters, page=page, size=size)
        counts = await self.log.counts(actor.tenant_id, team)
        kinds: dict[str, int] = {}
        targets: dict[str, int] = {}
        for (action, target), n in counts.items():
            kinds[KIND.get(action, "edited")] = kinds.get(KIND.get(action, "edited"), 0) + n
            targets[target] = targets.get(target, 0) + n
        views = {v: sum(n for (a, _), n in counts.items() if a in actions) for v, actions in VIEWS.items()}
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
            "facets": {"action": kinds, "targetType": targets},
            "viewCounts": {"all": sum(counts.values()), **views},
        }
