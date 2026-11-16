"""What `/v1/me` answers, read in five statements on the request's transaction, each portable to PostgreSQL and SQL
Server: the workspace's record with the caller's user row and the owner; every active team with the caller's
membership there, if any; the caller's role assignments; the grids of the roles they hold; and the policies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import sqlalchemy as sa

from ops_access import Grant
from ops_store import Guarantee

from .identity import User
from .lifecycle import WorkspaceState, owner_query
from .policies import PolicyValues, values_in
from .roles import Holdings, grids_in, holdings_with
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
    # Teams the caller is a member of, oldest membership first; then every other active team, oldest first.
    member_teams: list[MyTeam]
    other_teams: list[MyTeam]
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
        mine = members.c.user_id == user_id
        team_rows = (
            sa.select(teams.c.id, teams.c.name, members.c.role)
            .select_from(teams)
            .outerjoin(members, sa.and_(members.c.team_id == teams.c.id, mine, members.c.status == "active"))
            .where(teams.c.status == "active")
            # Member rows come in membership order, the rest (no membership columns) in the team's own; where a
            # database puts nulls does not matter, as the two are split below.
            .order_by(members.c.created_at, members.c.id, teams.c.created_at, teams.c.id)
        )
        async with self.tenant_tx(tenant_id) as c:
            row = (await c.execute(record)).first()
            if row is None or row[0] is None:
                return None
            found = (await c.execute(team_rows)).all()
            member_rows = [r for r in found if r[2] is not None]
            names = {str(r[0]): str(r[1]) for r in member_rows}
            held = await holdings_with(c, user_id, names)
            grids = await grids_in(c, sorted({a.role_id for a in held.assignments}))
            policies = await values_in(c)
        other_rows = [r for r in found if r[2] is None]
        return MeRows(
            user=User(tenant_id, str(row[0]), str(row[1]), str(row[2])),
            tenant_name=row[3],
            security_team=row[4],
            permission_version=int(row[5] or 0),
            workspace=WorkspaceState(status=row[6], closed_at=row[7], owner=row[8]),
            member_teams=[MyTeam(str(r[0]), str(r[1]), str(r[2])) for r in member_rows],
            other_teams=[MyTeam(str(r[0]), str(r[1]), None) for r in other_rows],
            holdings=held,
            grids=grids,
            policies=policies,
        )
