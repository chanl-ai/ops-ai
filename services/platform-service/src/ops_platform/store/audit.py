"""Audit entries written in the same transaction as the change they record (I7).

`record` is what every platform write calls inside its own `tenant_tx`, so the entry and the change commit together or
not at all. `TeamNameAudit` is that mechanism behind ops_store's `AuditPort`, so the shared audit suite can prove it:
renaming a team is the change, and an entry the store refuses (None) fails the rename too.
"""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee

from .tables import api_keys, audit_entries, members, teams, tenants, users
from .tenancy import TenantDb

# The console's action word for each platform action; the page filters and labels by these.
KIND = {
    "member.invite": "invited",
    "member.accept": "joined",
    "member.role": "role_changed",
    "member.remove": "deleted",
    "key.create": "created",
    "key.revoke": "revoked",
    "auth.sign_in": "login",
    "auth.sign_out": "login",
    "auth.step_up": "login",
    "auth.refresh_reuse": "revoked",
    "team.rename": "edited",
    "team.create": "created",
    "team.archive": "edited",
    "team.restore": "edited",
    "team.leave": "deleted",
    "team.delete": "deleted",
    "workspace.rename": "edited",
    "workspace.teams": "edited",
    "workspace.transfer": "role_changed",
    "workspace.leave": "deleted",
    "workspace.close": "deleted",
    "workspace.restore": "edited",
    "workspace.purge": "deleted",
    "policy.set": "edited",
    "access.check": "checked",
}

# Every route that changes a workspace or a team, and the audit action it writes in the same transaction (c-529). The
# route-table walk in tests/test_workspace_lifecycle.py fails on a changing route missing here or an action missing
# from KIND, so a new route says what it records before it ships.
ROUTE_ACTIONS: dict[tuple[str, str], str] = {
    ("POST", "/v1/settings/teams"): "team.create",
    ("PATCH", "/v1/settings/teams/{team_id}"): "team.rename",
    ("POST", "/v1/settings/teams/{team_id}/archive"): "team.archive",
    ("POST", "/v1/settings/teams/{team_id}/restore"): "team.restore",
    ("PATCH", "/v1/settings/workspace"): "workspace.rename",
    ("PUT", "/v1/settings/workspace-teams"): "workspace.teams",
    ("POST", "/v1/settings/members/invite"): "member.invite",
    ("POST", "/v1/settings/members/role"): "member.role",
    ("POST", "/v1/settings/members/delete"): "member.remove",
    ("POST", "/v1/workspace/transfer"): "workspace.transfer",
    ("POST", "/v1/workspace/leave"): "workspace.leave",
    ("POST", "/v1/workspace/close"): "workspace.close",
    ("POST", "/v1/workspace/restore"): "workspace.restore",
    ("POST", "/v1/settings/teams/{team_id}/leave"): "team.leave",
    ("DELETE", "/v1/settings/teams/{team_id}"): "team.delete",
}

# The audit page's views, as the platform actions each holds; platform-service records no publishes.
VIEWS: dict[str, frozenset[str]] = {
    "access": frozenset(a for a in KIND if a.startswith(("member.", "key."))),
    "deletions": frozenset(
        {"member.remove", "key.revoke", "team.delete", "workspace.close", "workspace.purge", "workspace.leave"}
    ),
    "publishes": frozenset(),
}


async def record(
    c: AsyncConnection,
    *,
    tenant_id: str,
    team_id: str | None,
    actor: str,
    action: str,
    target_kind: str,
    target_id: str,
    request_id: str,
    detail: dict[str, Any] | None,
) -> None:
    """One entry, on the caller's connection so it shares the caller's transaction. `detail` must not be None: the
    column refuses null, so a write that cannot say what it did fails as a whole."""
    await c.execute(
        audit_entries.insert().values(
            id=new_id("aud"),
            tenant_id=tenant_id,
            team_id=team_id,
            actor=actor,
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            request_id=request_id,
            at=now_iso(),
            detail=detail,
        )
    )


class TeamNameAudit:
    """Conformance adapter: one tenant and team per entity id, renamed with an audited write."""

    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    def __init__(self, db: TenantDb, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    @classmethod
    async def open(cls, url: str) -> TeamNameAudit:
        db = TenantDb.open(url)
        tenant_id = new_id("ten")
        # The tenants policy keys on the row's own id, so the new tenant is written as itself.
        async with db.tenant_tx(tenant_id) as c:
            await c.execute(
                tenants.insert().values(
                    id=tenant_id, name="conformance", status="active", allowed_domains=[], created_at=now_iso()
                )
            )
        return cls(db, tenant_id)

    async def apply(self, entity_id: str, value: str, entry: dict[str, Any] | None) -> None:
        async with self.db.tenant_tx(self.tenant_id) as c:
            updated = await c.execute(
                teams.update().where(teams.c.id == entity_id).values(name=value, name_key=value.lower())
            )
            if updated.rowcount == 0:
                await c.execute(
                    teams.insert().values(
                        id=entity_id,
                        tenant_id=self.tenant_id,
                        name=value,
                        owner_groups=[],
                        scope="all",
                        created_at=now_iso(),
                    )
                )
            await record(
                c,
                tenant_id=self.tenant_id,
                team_id=entity_id,
                actor="conformance",
                action="team.rename",
                target_kind="team",
                target_id=entity_id,
                request_id=new_id("req"),
                detail=entry,
            )

    async def value(self, entity_id: str) -> str | None:
        async with self.db.tenant_tx(self.tenant_id) as c:
            return (await c.execute(sa.select(teams.c.name).where(teams.c.id == entity_id))).scalar()

    async def entries(self, entity_id: str) -> int:
        q = sa.select(sa.func.count()).select_from(audit_entries).where(audit_entries.c.target_id == entity_id)
        async with self.db.tenant_tx(self.tenant_id) as c:
            return int((await c.execute(q)).scalar_one())


def _seen(team_id: str, account: bool) -> sa.ColumnElement[bool]:
    """The team's entries, and with `account` the ones no team holds."""
    own = audit_entries.c.team_id == team_id
    if not account:
        return own
    return sa.or_(own, audit_entries.c.team_id.is_(None), audit_entries.c.team_id == "")


class AuditLog:
    """Reads one team's entries, newest first, and with `account` the entries no team holds (sign-in, membership: the
    account's own records). Never another team's (c-507)."""

    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.RLS})

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def page(
        self,
        tenant_id: str,
        team_id: str,
        *,
        account: bool = False,
        filters: dict[str, str | None],
        page: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        where: list[Any] = [_seen(team_id, account)]
        for column in ("action", "actor", "target_kind"):
            if filters.get(column):
                where.append(audit_entries.c[column] == filters[column])
        if filters.get("view") in VIEWS:
            where.append(audit_entries.c.action.in_(sorted(VIEWS[str(filters["view"])])))
        if filters.get("kind"):
            where.append(audit_entries.c.action.in_([a for a, k in KIND.items() if k == filters["kind"]]))
        if filters.get("from"):
            where.append(audit_entries.c.at >= filters["from"])
        if filters.get("to"):
            where.append(audit_entries.c.at < filters["to"])
        # Names are joined here so the page shows people and targets without a second request per row; an actor or
        # target removed since keeps its id and shows no name.
        actor, person, target = users.alias("actor_user"), users.alias("target_user"), audit_entries.c.target_kind
        rows = (
            sa.select(
                audit_entries,
                actor.c.name.label("actor_name"),
                actor.c.email.label("actor_email"),
                teams.c.name.label("team_name"),
                sa.func.coalesce(members.c.email, api_keys.c.name, person.c.name).label("target_name"),
            )
            .outerjoin(actor, actor.c.id == audit_entries.c.actor)
            .outerjoin(teams, teams.c.id == audit_entries.c.team_id)
            .outerjoin(members, sa.and_(target == "member", members.c.id == audit_entries.c.target_id))
            .outerjoin(api_keys, sa.and_(target == "api_key", api_keys.c.id == audit_entries.c.target_id))
            # An access check is about a person: their name, so the line reads "Checked Maya Okafor's access".
            .outerjoin(person, sa.and_(target == "person", person.c.id == audit_entries.c.target_id))
            .where(*where)
            .order_by(audit_entries.c.at.desc(), audit_entries.c.id)
            .limit(size)
            .offset((page - 1) * size)
        )
        total = sa.select(sa.func.count()).select_from(audit_entries).where(*where)
        async with self.db.tenant_tx(tenant_id) as c:
            found = [dict(r) for r in (await c.execute(rows)).mappings().all()]
            count = int((await c.execute(total)).scalar_one())
        return found, count

    async def counts(self, tenant_id: str, team_id: str, *, account: bool = False) -> dict[tuple[str, str], int]:
        """Entries per (action, target kind): what the audit page's views and filters count."""
        q = (
            sa.select(audit_entries.c.action, audit_entries.c.target_kind, sa.func.count())
            .where(_seen(team_id, account))
            .group_by(audit_entries.c.action, audit_entries.c.target_kind)
        )
        async with self.db.tenant_tx(tenant_id) as c:
            return {(a, k): int(n) for a, k, n in (await c.execute(q)).all()}
