"""What a conversation already read, reused by its follow-ups.

A read's result is kept for a short time, keyed by the tool and its input; the caller keeps one cache per conversation
and person, so a person never reads another's results. A follow-up that makes the same read answers from the cache, and
the model is told the result is from earlier in the conversation. A successful write to an app forgets everything read
from that app, so a read after a save reads again.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

# How long a read is reused: long enough for the follow-ups of one exchange, short enough that a record changed in the
# app by someone else is read again soon.
KEEP_S = 300.0
# What the model is told a reused result is.
EARLIER = "This is the result of the same call from earlier in this chat; it was not read again."


@dataclass(frozen=True)
class Kept:
    output: Any
    # What the model was told in place of the output (a masked or worded result), told again on reuse.
    for_model: Any
    at: float


@dataclass
class ToolCache:
    """One conversation's reads, for one person."""

    keep_s: float = KEEP_S
    clock: Callable[[], float] = time.monotonic
    entries: dict[tuple[str, str, str], Kept] = field(default_factory=dict[tuple[str, str, str], Kept])

    def get(self, app: str, tool: str, input_hash: str) -> Kept | None:
        """This read as it came back, or None when there is none or it is older than keep_s."""
        kept = self.entries.get((app, tool, input_hash))
        if kept is None:
            return None
        if self.clock() - kept.at > self.keep_s:
            self.entries.pop((app, tool, input_hash), None)
            return None
        return kept

    def put(self, app: str, tool: str, input_hash: str, output: Any, for_model: Any = None) -> None:
        self.entries[(app, tool, input_hash)] = Kept(output, for_model, self.clock())

    def idle(self) -> bool:
        """Nothing kept is still fresh: the caller may drop this cache."""
        now = self.clock()
        return all(now - k.at > self.keep_s for k in self.entries.values())

    def wrote(self, app: str) -> None:
        """A write to `app` succeeded: what was read from it may have changed."""
        for key in [k for k in self.entries if k[0] == app]:
            self.entries.pop(key, None)


class ToolCaches(Protocol):
    """The cache of the conversation and person the current call is made for, or None where reads are not reused."""

    async def current(self) -> ToolCache | None: ...
