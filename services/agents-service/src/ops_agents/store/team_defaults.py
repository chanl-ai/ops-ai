"""The agent each team's new chats start on (c-174). Provisioning writes a team's first row; a team admin changes it.
No row means no default: nothing in the code names one."""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.schema import TENANT_SCOPED

from .base import metadata
from .tenancy import current_tenant, tenant_tx

team_default_agents = sa.Table(
    "team_default_agents",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
    sa.Column("team_id", sa.String(64), primary_key=True),
    sa.Column("agent_id", sa.String(64), nullable=False),
    sa.Column("updated_by", sa.String(320), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    info=TENANT_SCOPED,
)


class TeamDefaults:
    # One row per team, replaced whole: the last admin to pick a default wins, so no write depends on what was read.
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def agent(self, team_id: str) -> str | None:
        """The team's default agent id, or None before one is set."""
        async with tenant_tx(self.engine) as c:
            q = sa.select(team_default_agents.c.agent_id).where(team_default_agents.c.team_id == team_id)
            return (await c.execute(q)).scalar()

    async def set_agent(self, team_id: str, agent_id: str, *, by: str) -> None:
        values = {"agent_id": agent_id, "updated_by": by, "updated_at": now_iso()}
        try:
            async with tenant_tx(self.engine) as c:
                await c.execute(team_default_agents.insert().values(team_id=team_id, **values))
        except IntegrityError:
            async with tenant_tx(self.engine) as c:
                await c.execute(
                    team_default_agents.update()
                    .where(
                        team_default_agents.c.tenant_id == current_tenant(),
                        team_default_agents.c.team_id == team_id,
                    )
                    .values(**values)
                )
