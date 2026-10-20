"""What the caller may do with one record, for a detail response (c-186): the console shows View only and hides
buttons from these flags instead of guessing from the caller's role. Each flag runs the check the record's own write
route runs, so the page and the route never disagree."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ops_service_kit.errors import Conflict, Forbidden, NotFound

ACTIONS = ("edit", "delete", "publish")


async def rights(check: Callable[[str], Awaitable[Any]], words: dict[str, str] | None = None) -> dict[str, bool]:
    """`canEdit`, `canDelete` and `canPublish`: whether `check(action)` passes, with `words` mapping an action to the
    word its route passes (a widget is saved and retired). A record the caller cannot change at all (another team's,
    or a seeded one) answers False rather than the route's error."""
    out: dict[str, bool] = {}
    for action in ACTIONS:
        try:
            await check((words or {}).get(action, action))
        except (Forbidden, NotFound, Conflict):
            out[f"can{action.capitalize()}"] = False
        else:
            out[f"can{action.capitalize()}"] = True
    return out
