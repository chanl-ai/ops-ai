"""The record one agent's call to another carries: who the chain runs for, where it started and the agents on it.

It is made when an agent asks a specialist and kept on the specialist's thread, so a turn resumed after an approval
reads the same record. The budget left is not a field: it is the root thread's budget less what the chain has spent,
read from the ledger when it is needed, so the record never holds a stale number.
"""

from __future__ import annotations

from .chat import WireModel


class ChainRecord(WireModel):
    # Who the chain runs for: the person's email, or the service identity's subject when a service started the run.
    started_for: str
    # The thread and run the person's request arrived on; the chain spends from this thread's budget.
    root_thread_id: str
    root_run_id: str | None = None
    # The agents on the chain in call order, each as `<id>@v<version>`, the asking agent first.
    path: list[str]
    # How many calls deep the last agent on the path is; the first agent is 0.
    depth: int

    def names(self, agent_id: str) -> bool:
        """Whether `agent_id` is already on the path, at any version."""
        return any(step.split("@", 1)[0] == agent_id for step in self.path)
