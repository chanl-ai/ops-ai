"""Each chat's reads, kept per thread and person so a follow-up reuses them (ops_agent_kernel/tool_cache.py).

Only a chat run with a known person reuses reads: a workflow reads every time, and a call made on the team's account
reads every time, since the team may see other records than the person. The caches live in this process, so a turn
another process runs reads again, which costs a call and nothing else.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable

from ops_agent_kernel.tool_cache import KEEP_S, ToolCache

from ..activities.gateway import current_run_context
from .run_person import RUN_PERSON

# The chats whose reads are kept at once; the least recently used are dropped past it.
CHATS = 500


class ChatReads:
    def __init__(self, *, limit: int = CHATS, keep_s: float = KEEP_S, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.keep_s = keep_s
        self.clock = clock
        self.caches: OrderedDict[tuple[str, str], ToolCache] = OrderedDict()

    async def current(self) -> ToolCache | None:
        chat = RUN_PERSON.get()
        if chat is None or not chat.email or not chat.thread or current_run_context().team_account:
            return None
        key = (chat.thread, chat.email)
        cache = self.caches.pop(key, None) or ToolCache(keep_s=self.keep_s, clock=self.clock)
        self.caches[key] = cache
        while len(self.caches) > self.limit:
            self.caches.popitem(last=False)
        for other in [k for k, c in self.caches.items() if k != key and c.idle()]:
            del self.caches[other]
        return cache
