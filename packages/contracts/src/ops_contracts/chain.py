"""The record one agent's call to another carries: who the chain runs for, where it started and the agents on it.

It is made when an agent asks a specialist and kept on the specialist's thread, so a turn resumed after an approval
reads the same record. The budget left is not a field: it is the root thread's budget less what the chain has spent,
read from the ledger when it is needed, so the record never holds a stale number.

`ChainRecord.extended` is the one rule for who may be asked next: it is what offers an agent to a turn and what
refuses a call the turn makes, so the two cannot disagree.
"""

from __future__ import annotations

from typing import Literal

from .chat import WireModel

# How many calls deep a chain may go: 1 lets the first agent ask a specialist, which asks no one.
MAX_DEPTH = 1

REFUSALS: dict[str, str] = {
    "agent_on_path": "That agent is already on this chain of calls, so it is not asked again.",
    "chain_too_deep": "This chain of calls is as deep as it may go, so no further agent is asked.",
}


class ChainRefusedError(Exception):
    """An agent that may not be added to a chain: it is already on the path, or the chain is at its depth."""

    def __init__(self, code: Literal["agent_on_path", "chain_too_deep"]) -> None:
        super().__init__(REFUSALS[code])
        self.code = code
        self.message = REFUSALS[code]


def _step(agent_id: str, version: int) -> str:
    return f"{agent_id}@v{version}"


class ChainRecord(WireModel):
    # Who the chain runs for: the person's email, the service identity's subject when a service started the run, or
    # `agent:<id>` for a run with no person, which acts as its agent.
    started_for: str
    # The thread and run the person's request arrived on; the chain spends from this thread's budget.
    root_thread_id: str
    root_run_id: str | None = None
    # The agents on the chain in call order, each as `<id>@v<version>`, the asking agent first.
    path: list[str]
    # How many calls deep the last agent on the path is; the first agent is 0.
    depth: int
    # The deepest a call on this chain may be, fixed when the chain starts.
    max_depth: int = 1

    @classmethod
    def starting(
        cls, *, agent_id: str, version: int, started_for: str, thread_id: str, run_id: str | None
    ) -> ChainRecord:
        """The chain of a turn nobody asked: its agent alone, on the thread the request arrived on."""
        return cls(
            started_for=started_for,
            root_thread_id=thread_id,
            root_run_id=run_id,
            path=[_step(agent_id, version)],
            depth=0,
            max_depth=MAX_DEPTH,
        )

    def names(self, agent_id: str) -> bool:
        """Whether `agent_id` is already on the path, at any version."""
        return any(step.split("@", 1)[0] == agent_id for step in self.path)

    def extended(self, agent_id: str, version: int) -> ChainRecord:
        """This chain with `agent_id` asked by its last agent; ChainRefusedError when it may not be asked."""
        if self.names(agent_id):
            raise ChainRefusedError("agent_on_path")
        if self.depth >= self.max_depth:
            raise ChainRefusedError("chain_too_deep")
        return self.model_copy(update={"path": [*self.path, _step(agent_id, version)], "depth": self.depth + 1})
