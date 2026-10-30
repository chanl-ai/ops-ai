"""How the engine's store reaches its tables under the caller's tenancy rules. The engine never decides tenancy: the
host (agents-service) implements this with its row-level-security transactions, so engine rows get the same forced RLS
as every other tenant table."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


class Transactions(Protocol):
    engine: AsyncEngine

    def tenant(self) -> str:
        """The tenant the current request or claimed work acts for; raises when none is set."""
        ...

    def tenant_tx(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """A transaction that sees and writes only the current tenant's rows."""
        ...

    async def check_fence(self, conn: AsyncConnection, thread_id: str, generation: int | None) -> None:
        """Raises LeaseSupersededError inside `conn`'s transaction when the thread's lease generation is no longer
        `generation`; None checks nothing."""
        ...

    def system_tx(self, reason: str) -> AbstractAsyncContextManager[AsyncConnection]:
        """A transaction past row-level security, for claiming work before its tenant is known; `reason` is one of the
        constants below, logged by the host. Nothing else."""
        ...


# Why the engine reads past the tenant (`Transactions.system_tx`).
CLAIM_WORK = "engine_claim_work"  # the worker claims the next due engine_work row of any tenant
LIVE_WORKFLOWS = "engine_live_workflows"  # the mailbox listener lists every tenant's live workflows
RECONCILE_RUNS = "engine_reconcile_runs"  # the reconciler finds runs with nothing behind them, then acts per tenant
