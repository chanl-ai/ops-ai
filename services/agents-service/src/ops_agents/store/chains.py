"""Which thread's budget a thread's model calls spend from, read from what api/agent_calls.py writes on a
specialist's thread. The budget itself is the model gateway's (api/budgets.py)."""

from __future__ import annotations

import sqlalchemy as sa
from pydantic import JsonValue

from ops_store.team_scope import team_visible

from .graphs import graph_threads
from .tenancy import RuntimeStore


def asked_by(meta: JsonValue) -> str | None:
    """The thread whose agent asked this thread's agent, from the two keys api/agent_calls.py writes on a specialist's
    thread; None for any other thread, a workflow an agent started included, whose spend stays on its own budget.
    Neither key can come from a request body (routers/graphs.py SERVER_META)."""
    if not isinstance(meta, dict):
        return None
    parent = meta.get("parentThreadId")
    return str(parent) if parent and meta.get("calledBy") else None


class ChainStore(RuntimeStore):
    async def chain_root(self, thread_id: str) -> str:
        """The thread whose budget a call on `thread_id` counts against: itself, or for a specialist's thread the
        thread its chain started on."""
        t = graph_threads.c
        async with self.tx() as c:
            row = (await c.execute(sa.select(t.meta).where(t.id == thread_id, team_visible(graph_threads)))).first()
        meta: JsonValue = row[0] if row is not None else None
        asked = asked_by(meta)
        if asked is None or not isinstance(meta, dict):
            return thread_id
        chain = meta.get("chain")
        return str((chain.get("rootThreadId") if isinstance(chain, dict) else None) or asked)

    async def team_of(self, thread_id: str) -> str | None:
        t = graph_threads.c
        async with self.tx() as c:
            row = (await c.execute(sa.select(t.team_id).where(t.id == thread_id, team_visible(graph_threads)))).first()
        return str(row[0]) if row is not None else None
