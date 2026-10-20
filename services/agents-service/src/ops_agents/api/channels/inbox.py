"""Delivering an inbound message to an existing case. Where it goes depends on the thread's state:

- waiting on a person (a pending interrupt): delivered now, and the human step's SLA clock restarts (E5);
- mid-run (its lease is held, or held by a crashed owner the sweeper will recover): the deployment's multitask rule
  decides, enqueue by default, and queued messages are delivered in arrival order when the run ends;
- closed (the graph has finished): refused, so the channel opens a follow-up case linked to it.
"""

from __future__ import annotations

from typing import Any, Literal

from ops_service_kit.errors import Conflict
from ops_service_kit.ids import now_iso

from ...store.leases import thread_lock
from ..deps import Runtime
from ..runs import config, graph_store, pending, require_graphs, resolve
from ..timers import restart_on_customer_reply, waiting_with_sla

Outcome = Literal["delivered", "queued"]


class ThreadClosedError(Conflict):
    code = "thread_closed"


async def deliver(rt: Runtime, thread_id: str, *, key: str, kind: str, payload: Any) -> tuple[Outcome, int]:
    """Adds the message to the thread's inbox once (a redelivery returns the first outcome)."""
    require_graphs(rt)
    assert rt.channels is not None and rt.leases is not None
    row, graph = await resolve(rt, thread_id)
    async with graph_store(rt).engine.begin() as c:
        # Held to commit: no run can take the lease between the look at the thread below and the inbox write.
        await thread_lock(c, thread_id)
        lease = await rt.leases.held(thread_id)
        if lease is not None:
            deployment = await rt.channels.deployment(row["deployment_id"]) if row.get("deployment_id") else None
            if deployment is not None and deployment.multitask == "reject":
                raise Conflict(
                    "The case is mid-run and its deployment refuses messages until it finishes.", code="run_active"
                )
            status, seq = await rt.channels.add_to_inbox(
                c, thread_id, key, kind=kind, payload=payload, status="queued", now=now_iso()
            )
            return ("queued" if status == "queued" else "delivered"), seq
        snap = await graph.aget_state(config(thread_id))
        if not snap.created_at:
            # The case exists but its first run has not started (another poller is opening it): the first run's end
            # delivers it, like a message that arrives mid-run.
            status, seq = await rt.channels.add_to_inbox(
                c, thread_id, key, kind=kind, payload=payload, status="queued", now=now_iso()
            )
            return ("queued" if status == "queued" else "delivered"), seq
        if pending(snap):
            status, seq = await rt.channels.add_to_inbox(
                c, thread_id, key, kind=kind, payload=payload, status="delivered", now=now_iso()
            )
        elif snap.next:
            # Mid-run with no lease (a run that never started, or one that errored): queue for the next run.
            status, seq = await rt.channels.add_to_inbox(
                c, thread_id, key, kind=kind, payload=payload, status="queued", now=now_iso()
            )
            return ("queued" if status == "queued" else "delivered"), seq
        else:
            raise ThreadClosedError("This case has finished; open a follow-up case linked to it.")
    if kind == "customer_reply" and await waiting_with_sla(rt, thread_id):
        await restart_on_customer_reply(rt, thread_id)
    return "delivered", seq


async def drain(rt: Runtime, thread_id: str) -> list[int]:
    """After a run ends: if the thread now waits on a person, deliver what queued up during the run, in order, and
    restart the SLA clock once. A thread that finished keeps its queued messages for the channel to route."""
    if rt.channels is None:
        return []
    _, graph = await resolve(rt, thread_id)
    if not pending(await graph.aget_state(config(thread_id))):
        return []
    delivered = await rt.channels.deliver_queued(thread_id, now_iso())
    if delivered and await waiting_with_sla(rt, thread_id):
        await restart_on_customer_reply(rt, thread_id)
    return delivered
