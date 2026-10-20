"""How the sweeper and the timer poller work one claimed thread under its own tenant.

They claim before they know the tenant, so they read it from the thread's row past row-level security
(`GraphStore.tenant_of`), then do the work in a new task that sets it. Setting it inside that task, never on the loop's
own context, means two threads of different tenants worked by one sweep cannot see each other's rows.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ops_store import isolation

from ..store.tenancy import THREAD_WORK
from .deps import Runtime
from .runs import graph_store


async def as_thread_tenant[T](rt: Runtime, thread_id: str, work: Callable[[], Awaitable[T]]) -> T | None:
    """`work()` under the thread's tenant, in its own task; None when the thread does not exist."""
    tenant = await graph_store(rt).tenant_of(thread_id)
    if tenant is None:
        return None

    async def scoped() -> T | _Raised:
        with isolation.tenant_wide(THREAD_WORK, tenant_id=tenant):
            try:
                return await work()
            except BaseException as e:
                # A task re-raises SystemExit and KeyboardInterrupt into the event loop instead of to its awaiter;
                # carried out and raised here, they reach the loop's caller as they would without the task.
                return _Raised(e)

    result = await asyncio.create_task(scoped())
    if isinstance(result, _Raised):
        raise result.error
    return result


class _Raised:
    def __init__(self, error: BaseException) -> None:
        self.error = error
