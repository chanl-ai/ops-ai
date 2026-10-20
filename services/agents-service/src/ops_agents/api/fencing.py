"""On takeover, the new owner raises tools-service's fence before it resumes the thread (E2c).

The tools-service fence otherwise rises only when a write arrives, so between a takeover and the new owner's first
tool write a stalled old owner could still write with its old generation. Raising the fence first closes that
window. If tools-service cannot be reached the takeover goes on, with a warning journaled on the thread: the new
owner's first tool write raises the fence anyway, and the window stays open only until then.
"""

from __future__ import annotations

from ops_agents.activities.gateway import GatewayClient
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.logging import get_logger

from ..store.graphs import GraphStore

log = get_logger("ops_agents.api.fencing")


class ToolsFence:
    def __init__(self, gateway: GatewayClient, store: GraphStore) -> None:
        self.gateway = gateway
        self.store = store

    async def __call__(self, thread_id: str, generation: int) -> None:
        try:
            await self.gateway.raise_fence(thread_id, generation)
        except Exception as e:  # The takeover must go on; the fence still rises with the new owner's first write.
            log.warning("tools_fence_not_raised", thread=thread_id, generation=generation, error=type(e).__name__)
            await self._warn(thread_id, generation, f"{type(e).__name__}: {e}")

    async def _warn(self, thread_id: str, generation: int, reason: str) -> None:
        run_id = new_id("run")
        event = {
            "event": "lease.fence_not_raised",
            "runId": run_id,
            "seq": 0,
            "data": {"generation": generation, "reason": reason},
        }
        try:
            await self.store.start_run(
                run_id, thread_id, "lease", now_iso(), {"fence": generation}, generation=generation
            )
            await self.store.finish_run(run_id, "done", [event], now_iso(), generation=generation)
        except Exception as e:  # A thread with no row yet (or a lost journal) leaves the log line as the record.
            log.warning("tools_fence_warning_not_journaled", thread=thread_id, error=type(e).__name__)
