"""Which version of tools-service's declared team defaults each team has: a row per team the
reconciler brought up to date, so a new version reaches every team on the next start and a team already current is
not written again."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import Guarantee
from ops_store.dialect import upsert
from ops_store.schema import TEAM_OWNED
from ops_store.team_scope import acting_as, any_team, team_visible

from .modules import metadata

team_defaults = sa.Table(
    "team_defaults",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), primary_key=True),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
    info=TEAM_OWNED,
)

# Why the start-up catch-up reads every team's row: it brings each team's defaults to this release's version, and
# reads only versions, never a team's records.
CATCH_UP = "the start-up reconciler brings every team's defaults to this release's version"


class TeamDefaults:
    # One row per (tenant, team): recording a version is an upsert on that key.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def version(self, tenant_id: str, team_id: str) -> int:
        """The defaults version the team has; 0 for a team never provisioned."""
        t = team_defaults
        with acting_as(team_id):
            q = sa.select(t.c.version).where(t.c.tenant_id == tenant_id, team_visible(t), t.c.team_id == team_id)
        async with self.engine.connect() as c:
            return int((await c.execute(q)).scalar() or 0)

    async def record(self, tenant_id: str, team_id: str, version: int, at: datetime) -> None:
        row = {"tenant_id": tenant_id, "team_id": team_id, "version": version, "applied_at": at}
        async with self.engine.begin() as c:
            await c.execute(upsert(c, team_defaults, row, keys=["tenant_id", "team_id"]))

    async def behind(self, version: int) -> list[tuple[str, str]]:
        """Every (tenant, team) whose defaults are older than `version`."""
        t = team_defaults
        q = sa.select(t.c.tenant_id, t.c.team_id).where(any_team(t, CATCH_UP), t.c.version < version)
        async with self.engine.connect() as c:
            return [(str(r.tenant_id), str(r.team_id)) for r in await c.execute(q)]
