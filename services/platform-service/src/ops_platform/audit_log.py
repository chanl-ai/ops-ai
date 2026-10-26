"""Reading the audit log (I7): admins only, their team's entries, or every entry in the tenant when the team's scope
is `all` (the platform team). Entries are written by each store in the transaction of the write they record."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil
from typing import Any

from ops_access import ANY_TEAM
from ops_service_kit.errors import Forbidden

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
        "team.create": lambda: f"Created the team {d.get('name', target)}",
        "team.archive": lambda: f"Archived the team {target}",
        "team.restore": lambda: f"Restored the team {target}",
        "team.leave": lambda: "Left the team",
        "team.delete": lambda: f"Deleted the team {target}",
        "workspace.rename": lambda: f"Renamed the workspace to {d.get('to', target)}",
        "workspace.teams": lambda: "Changed the workspace's security and default teams",
        "workspace.transfer": lambda: "Transferred the workspace to another account admin",
        "workspace.leave": lambda: "Left the workspace",
        "workspace.close": lambda: "Deleted the workspace; it can be restored until its records are removed",
        "workspace.restore": lambda: "Restored the workspace",
        "workspace.purge": lambda: "Removed the closed workspace's records",
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

    async def _account_admin(self, actor: Actor) -> bool:
        try:
            await self.members.require_admin(replace(actor, team_id=ANY_TEAM), "audit", "view")
        except Forbidden:
            return False
        return True

    async def page(self, actor: Actor, filters: dict[str, str | None], page: int, size: int) -> dict[str, Any]:
        await self.members.require_admin(actor, "audit", "view")
        # The acting team's entries; the account's own (no team) only for whoever reads audit in every team, the
        # account admin (owner's answer, c-507 Q1). No team reads another team's.
        account = await self._account_admin(actor)
        team = actor.team_id
        rows, total = await self.log.page(actor.tenant_id, team, account=account, filters=filters, page=page, size=size)
        counts = await self.log.counts(actor.tenant_id, team, account=account)
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
