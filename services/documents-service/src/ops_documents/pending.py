"""How many items of one of this process's queues are waiting or running, so `drain` can wait for none without holding
the tasks themselves (they run on the lifespan's supervisor, `ops_store.background`)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


def _none_yet() -> asyncio.Event:
    none = asyncio.Event()
    none.set()
    return none


@dataclass
class Pending:
    count: int = 0
    _none: asyncio.Event = field(default_factory=_none_yet)

    def add(self) -> None:
        self.count += 1
        self._none.clear()

    def done(self, n: int = 1) -> None:
        self.count -= n
        if self.count <= 0:
            self.count = 0
            self._none.set()

    async def none(self) -> None:
        """Returns once nothing is waiting or running."""
        await self._none.wait()
