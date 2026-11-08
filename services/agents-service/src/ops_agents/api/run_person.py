"""The person a chat thread's run acts for, whichever path runs it.

A chat turn's request sets TURN_PERSON while it streams. A run of the same thread started any other way (recovered
after a restart, resumed after an approval or a budget answer, a timer) has no request: it acts for the thread's
person, its owner, or for a child thread the person its parent acted for (`startedFor`). A chat thread with neither
acts for nobody, and its calls are refused rather than made as the team (acting_for.CallPeople).
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, cast

# The agent graph a chat thread runs (chat_threads.CHAT_GRAPH).
CHAT_GRAPH = "agent_wrapper"


@dataclass(frozen=True)
class RunPerson:
    """A chat run's person; `email` None when the thread names none."""

    email: str | None
    # The chat thread the run belongs to.
    thread: str | None = None


RUN_PERSON: ContextVar[RunPerson | None] = ContextVar("ops_run_person", default=None)


def person_of_thread(row: dict[str, Any]) -> RunPerson | None:
    """The person a run of this thread acts for, or None for a thread that is not a chat (a workflow's runs act for
    their starter, read from the run itself)."""
    if row.get("graph") != CHAT_GRAPH:
        return None
    meta = cast(dict[str, Any], row.get("meta") or {})
    email = str(meta.get("ownerEmail") or meta.get("startedFor") or "")
    return RunPerson(email if "@" in email else None, str(row.get("id") or "") or None)


@contextmanager
def running_for(row: dict[str, Any]) -> Generator[None]:
    token = RUN_PERSON.set(person_of_thread(row))
    try:
        yield
    finally:
        RUN_PERSON.reset(token)
