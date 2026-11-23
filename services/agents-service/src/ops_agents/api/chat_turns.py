"""A chat reply as queue work: one `engine_work` row of kind `turn` per reply, claimed through the engine's fair claim
and team cap (ops_engine/store/work.py).

The route queues the turn and claims its own row at once, so the process the person is connected to runs it and
streams it, renewing the claim beside the thread's lease. When that process dies, the claim lapses and a workflow
worker takes the row (ops_engine/worker.py `_turn`) and continues the thread from its last checkpoint here, with the
turn's id as the key of its model calls and writes (graphs/metering.py `step_calls`): the re-run pays for no model
call twice and sends no write under a new key. The row's `run_id` is its thread; its payload names the turn (the
reply's first run id). A team at its cap is refused at enqueue with `team_at_capacity`, and a turn past
`turn_deadline_seconds` from when it was queued is ended rather than continued.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager

from ops_engine.store import Work, WorkQueue
from ops_engine.worker import TURN
from ops_service_kit.errors import TooManyRequests
from ops_service_kit.http import Json
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.logging import get_logger
from ops_service_kit.narrow import an_object
from ops_store import isolation

from ..graphs.metering import step_calls
from ..store.engine import EngineTransactions
from .deps import Runtime
from .runs import graph_store
from .sweeper import recover

log = get_logger("ops_agents.api.chat_turns")

AT_CAPACITY = "Your team is already running as many replies as it may at once. Please try again shortly."


def turn_queue(rt: Runtime) -> WorkQueue:
    assert rt.leases is not None
    return WorkQueue(EngineTransactions(rt.db), rt.leases.owner, rt.leases.ttl, team_cap=rt.settings.engine_team_cap)


async def refuse_at_capacity(rt: Runtime, team_id: str) -> None:
    """Refuses a new reply while the team's live claims are at its cap, before the reply takes its thread."""
    cap = rt.settings.engine_team_cap
    if cap is not None and await turn_queue(rt).live(team_id) >= cap:
        raise TooManyRequests(AT_CAPACITY, code="team_at_capacity")


async def enqueue(rt: Runtime, thread_id: str, team_id: str, turn_id: str) -> Work:
    """Queues the reply `turn_id` and claims it for this process, which runs it."""
    queue = turn_queue(rt)
    row, _ = await queue.enqueue(
        thread_id,
        TURN,
        f"turn:{turn_id}",
        {"threadId": thread_id, "turnId": turn_id, "teamId": team_id},
        team_id=team_id,
    )
    work = await queue.take(int(row["id"]))
    assert work is not None, "a turn just queued is taken by the process that queued it"
    return work


def take_over(rt: Runtime) -> Callable[[Work], Awaitable[float | None]]:
    """The worker's turn handler: continues a turn whose process died, from its thread's last checkpoint."""

    async def turn(work: Work) -> float | None:
        thread_id, turn_id = work.run_id, str(_payload(work).get("turnId") or "")
        leases = rt.leases
        assert leases is not None

        async def go() -> float | None:
            lease = await leases.held(thread_id)
            if lease is None:
                return None  # the reply ended and let its thread go; only its row's done mark was lost
            if not any(x.thread_id == thread_id for x in await leases.expired()):
                return leases.ttl  # its process is still renewing the thread: look again after one lease
            with step_calls(turn_id):
                await recover(rt, thread_id, lease.run_id, dead_owner=lease.owner, dead_generation=lease.generation)
            return None

        with _in_turn_team(work):
            return await go()

    return turn


def end_late(rt: Runtime) -> Callable[[Work, str], Awaitable[None]]:
    """The worker's ending of a turn past its time limit: its run is recorded as stopped with `reason`, and its
    thread is let go so the next message can start."""

    async def end(work: Work, reason: str) -> None:
        thread_id = work.run_id
        leases = rt.leases
        assert leases is not None

        async def go() -> None:
            store, lease = graph_store(rt), await leases.held(thread_id)
            if lease is not None and not any(x.thread_id == thread_id for x in await leases.expired()):
                return  # still running on its own process, which ends it at its own deadline
            run_id = new_id("run")
            generation = await leases.acquire(thread_id, run_id)
            try:
                if lease is not None:
                    await store.mark_crashed(
                        lease.run_id, now_iso(), owner=lease.owner, running=[], generation=lease.generation,
                        by_generation=generation,
                    )  # fmt: skip
                await store.start_run(
                    run_id, thread_id, "timeout", now_iso(), {"ends": lease.run_id if lease else None}
                )
                ended: list[Json] = [{"event": "error", "runId": run_id, "seq": 0, "data": {"message": reason}}]
                await store.finish_run(run_id, "error", ended, now_iso(), generation=generation)
                await store.set_thread_status(thread_id, "idle", now_iso(), generation=generation)
            finally:
                await leases.release(thread_id, run_id)
            log.info("chat_turn_ended_late", thread=thread_id, run=run_id)

        with _in_turn_team(work):
            await go()

    return end


def _in_turn_team(work: Work) -> AbstractContextManager[object]:
    """The turn's tenant and team, as its row names them: no read past row-level security to find them."""
    return isolation.scope(work.tenant_id, str(_payload(work).get("teamId") or "") or None)


def _payload(work: Work) -> Json:
    return an_object(work.payload or {}, "a turn's payload")
