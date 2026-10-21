"""The graph journal as the checkpointer's prune guard: graph_runs is the long-term record of what a thread did."""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import Guarantee
from ops_store.team_scope import team_visible

from .graphs import graph_runs, graph_threads
from .leases import thread_leases
from .tenancy import tenant_tx

# Statuses a thread can be resumed from. "interrupted" waits on a person and "busy" is mid-run; both need history.
OPEN_STATUSES = ("busy", "interrupted")


class GraphJournal:
    # Reads only: whether a thread still needs its checkpoint history.
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def closed_with_journal(self, thread_id: str) -> bool:
        """True when the thread is not running, paused or leased, and at least one finished run of it is recorded."""
        finished = (
            sa.select(sa.literal(1))
            .where(graph_runs.c.thread_id == thread_id, graph_runs.c.finished_at.is_not(None))
            .exists()
        )
        running = (
            sa.select(sa.literal(1))
            .where(graph_runs.c.thread_id == thread_id, graph_runs.c.status == "running")
            .exists()
        )
        # Any lease blocks pruning, expired ones included: an expired lease is a crashed run the sweeper has yet to
        # continue from this very checkpoint.
        leased = (
            sa.select(sa.literal(1))
            .where(thread_leases.c.thread_id == thread_id, thread_leases.c.released_at.is_(None))
            .exists()
        )
        query = sa.select(graph_threads.c.id).where(
            graph_threads.c.id == thread_id,
            graph_threads.c.status.not_in(OPEN_STATUSES),
            team_visible(graph_threads),
            finished,
            ~running,
            ~leased,
        )
        async with tenant_tx(self.engine) as c:
            return (await c.execute(query)).first() is not None
