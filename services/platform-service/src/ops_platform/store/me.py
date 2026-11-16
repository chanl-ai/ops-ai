"""What `/v1/me` answers, read on the request's transaction in statements portable to PostgreSQL and SQL Server: the
workspace's record with the caller's user row and the owner; the active teams the caller is a member of; the caller's
role assignments; the grids of the roles they hold; and the policies. Only a workspace admin, decided by `can` on those
rows, has a sixth read: every other active team, which they act in through their workspace role.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import sqlalchemy as sa

from ops_access import ANY_TEAM, Grant
from ops_store import Guarantee

from .identity import User
from .lifecycle import WorkspaceState, owner_query
from .policies import PolicyValues, values_in
from .roles import Holdings, access_from, grids_in, holdings_with
from .tables import members, teams, tenants, users
from .tenancy import TenantDb


@dataclass(frozen=True)
class MyTeam:
    """An active team, with the caller's role there when they are a member of it."""

    id: str
    name: str
    role: str | None


@dataclass(frozen=True)
class MeRows:
    user: User
    tenant_name: str | None
    security_team: str | None
    permission_version: int
    workspace: WorkspaceState
    # Teams the caller is a member of, oldest membership first; for a workspace admin, every other active team, oldest
    # first (empty for anyone else).
    member_teams: list[MyTeam]
    other_teams: list[MyTeam]
    workspace_admin: bool
    holdings: Holdings
    grids: dict[str, list[Grant]]
    policies: PolicyValues


class MeStore(TenantDb):
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    async def read(self, tenant_id: str, user_id: str) -> MeRows | None:
        """None when the caller is not an active user of the workspace."""
        record = (
            sa.select(
                users.c.id,
                users.c.email,
                users.c.name,
                tenants.c.name,
                tenants.c.security_team_id,
                tenants.c.permission_version,
                tenants.c.status,
                tenants.c.closed_at,
                owner_query(tenant_id).limit(1).scalar_subquery(),
            )
            .select_from(tenants)
            .outerjoin(
                users, sa.and_(users.c.tenant_id == tenants.c.id, users.c.id == user_id, users.c.status == "active")
            )
            .where(tenants.c.id == tenant_id)
        )
        member_rows = (
            sa.select(teams.c.id, teams.c.name, members.c.role)
            .join(members, members.c.team_id == teams.c.id)
            .where(members.c.user_id == user_id, members.c.status == "active", teams.c.status == "active")
            .order_by(members.c.created_at, members.c.id)
        )
        async with self.tenant_tx(tenant_id) as c:
            row = (await c.execute(record)).first()
            if row is None or row[0] is None:
                return None
            mine = (await c.execute(member_rows)).all()
            held = await holdings_with(c, user_id, {str(r[0]): str(r[1]) for r in mine})
            grids = await grids_in(c, sorted({a.role_id for a in held.assignments}))
            policies = await values_in(c)
            admin = await _workspace_admin(tenant_id, user_id, held, grids, version=int(row[5] or 0), security=row[4])
            others: list[MyTeam] = []
            if admin:
                # A workspace admin acts in every team through their workspace role (RoleStore.workspace_admin).
                member_of = {str(r[0]) for r in mine}
                every = sa.select(teams.c.id, teams.c.name).where(teams.c.status == "active")
                every = every.order_by(teams.c.created_at, teams.c.id)
                others = [MyTeam(str(r[0]), str(r[1]), None) for r in (await c.execute(every)).all()]
                others = [t for t in others if t.id not in member_of]
        return MeRows(
            user=User(tenant_id, str(row[0]), str(row[1]), str(row[2])),
            tenant_name=row[3],
            security_team=row[4],
            permission_version=int(row[5] or 0),
            workspace=WorkspaceState(status=row[6], closed_at=row[7], owner=row[8]),
            member_teams=[MyTeam(str(r[0]), str(r[1]), str(r[2])) for r in mine],
            other_teams=others,
            workspace_admin=admin,
            holdings=held,
            grids=grids,
            policies=policies,
        )


async def _workspace_admin(
    tenant_id: str, user_id: str, held: Holdings, grids: dict[str, list[Grant]], *, version: int, security: str | None
) -> bool:
    """`RoleStore.workspace_admin`, decided by `can` on the rows already read rather than on a read of its own."""

    async def fetch(_t: str, _v: int, ids: list[str]) -> dict[str, list[Grant]]:
        return {i: grids[i] for i in ids if i in grids}

    p, access = await access_from(tenant_id, user_id, held, version=version, security=security, fetch=fetch)
    # `from_any_team`: the token-less caller acts in no team, and `roles_in(p, "*")` reads only `*` assignments.
    return access.may(p, "access", "manage", team=ANY_TEAM, from_any_team=True)
