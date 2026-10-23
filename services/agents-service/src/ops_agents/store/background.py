"""Background processes' heartbeats and jobs in agents-service (c-516). The worker has no web port and several API
processes each run a sweeper and a timer poller, so their heartbeats live in the database, one row per process
instance. A job is one piece of work a process did for a team, written inside that team; a team reads its own in
Activity, an account admin reads every team's on Govern > Background."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.logging import get_logger
from ops_store import Guarantee
from ops_store.background import BY_KEY, DbHeartbeats, heartbeats_table
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.team_scope import any_team, team_visible

from .base import metadata
from .tenancy import SYSTEM_ROLE, current_team, current_tenant, system_tx, tenant_tx

log = get_logger(__name__)

Outcome = Literal["done", "retried", "failed"]

# Why the Background page reads jobs past the tenant: an account admin sees what every process did, for every team.
BACKGROUND_PAGE = "background_page"
# The newest jobs kept per process and tenant; older ones are deleted as new ones are written.
KEEP_PER_PROCESS = 500
PRUNE_EVERY = 50

background_heartbeats = heartbeats_table(metadata)

background_jobs = sa.Table(
    "background_jobs",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    sa.Column("team_id", sa.String(64), nullable=False, default=current_team),
    sa.Column("process", sa.String(64), nullable=False),
    # What the job did, in one plain sentence a team member reads in Activity.
    sa.Column("summary", sa.String(500), nullable=False),
    sa.Column("outcome", sa.String(16), nullable=False),
    sa.Column("at", sa.String(32), nullable=False, server_default=""),
    sa.Index("ix_background_jobs_at", "tenant_id", "at"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


def heartbeats(engine: AsyncEngine) -> DbHeartbeats:
    """The heartbeat store every agents-service process writes to, as the system role."""
    return DbHeartbeats(engine, background_heartbeats, role=SYSTEM_ROLE)


@dataclass
class Job:
    id: str
    tenant_id: str
    team_id: str
    process: str
    summary: str
    outcome: str
    at: str

    def as_wire(self, team_name: str | None = None) -> dict[str, Any]:
        process = BY_KEY.get(self.process)
        return {
            "id": self.id,
            "process": self.process,
            "processTitle": process.title if process else self.process,
            "summary": self.summary,
            "outcome": self.outcome,
            "teamId": self.team_id,
            "teamName": team_name,
            "at": self.at,
        }


class BackgroundJobs:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._written = 0

    async def record(self, process: str, summary: str, outcome: Outcome, *, team_id: str | None = None) -> None:
        """One job, in the current tenant and team (the process has switched into the job's team); `team_id` names the
        job's team where the process acts for its whole tenant (the mail listener). A job that cannot be logged is
        only warned about: the log must not undo the work it describes."""
        if process not in BY_KEY:
            raise ValueError(f"{process!r} is not a listed background process")
        try:
            await self._insert(process, summary, outcome, team_id=team_id)
        except Exception:
            log.warning("background_job_unlogged", process=process, exc_info=True)

    async def _insert(self, process: str, summary: str, outcome: Outcome, *, team_id: str | None) -> None:
        t = background_jobs
        row: dict[str, Any] = {"id": new_id("bjob"), "process": process, "summary": summary[:500]}
        row |= {"outcome": outcome, "at": now_iso()} | ({"team_id": team_id} if team_id else {})
        async with tenant_tx(self.engine) as c:
            await c.execute(t.insert().values(**row))
            self._written += 1
            if self._written % PRUNE_EVERY == 0:
                keep = sa.select(t.c.id).where(t.c.process == process, team_visible(t))
                keep = keep.order_by(t.c.at.desc()).limit(KEEP_PER_PROCESS)
                await c.execute(t.delete().where(t.c.process == process, t.c.id.not_in(keep.scalar_subquery())))

    async def visible(self, *, limit: int = 50, before: str | None = None) -> list[Job]:
        """The newest jobs the current context may read: the caller's teams, held by the database."""
        t = background_jobs
        q = sa.select(t).where(team_visible(t)).order_by(t.c.at.desc()).limit(limit)
        if before is not None:
            q = q.where(t.c.at < before)
        async with tenant_tx(self.engine) as c:
            return [Job(**dict(r)) for r in (await c.execute(q)).mappings()]

    async def latest_everywhere(self, tenant_id: str, *, limit: int = 50) -> list[Job]:
        """Every team's newest jobs in one tenant, for an account admin's Background page."""
        t = background_jobs
        everyone = any_team(t, "an account admin's Background page lists every team's jobs")
        q = sa.select(t).where(t.c.tenant_id == tenant_id, everyone).order_by(t.c.at.desc()).limit(limit)
        async with system_tx(self.engine, BACKGROUND_PAGE) as c:
            return [Job(**dict(r)) for r in (await c.execute(q)).mappings()]
