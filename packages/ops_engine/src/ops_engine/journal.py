"""The step journal's contract: one row per node attempt, keyed by run, node, iteration and attempt. The wrapper
(compiler.py) reads it before running a node and writes it around each attempt; the SQL implementation is
store/steps.py, and `MemoryJournal` serves the engine's own tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

# running: an attempt under way, or one whose process died (dangling). waiting: a review paused for a person.
# ok: recorded output, returned on any re-run. pinned: an output set before a test run. error: the attempt failed.
# abandoned: a dangling read or model attempt superseded by a new attempt.
StepStatus = Literal["running", "waiting", "ok", "pinned", "error", "abandoned"]


@dataclass(frozen=True)
class StepRow:
    run_id: str
    node_id: str
    iteration: int
    attempt: int
    status: StepStatus
    effects: str
    key: str
    input: Any = None
    port: str | None = None
    output: Any = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    # The writing worker's lease generation: begin and finish are refused once the run's lease has moved past it.
    generation: int | None = None
    # The node's type id; recorded so steps can be listed by kind (Activity's tool calls).
    node_type: str | None = None


class RunCancelledError(RuntimeError):
    """The run was cancelled, so no new attempt begins. An attempt that began before the cancel runs to its end and is
    recorded; the pass stops at the next step."""


class Journal(Protocol):
    async def steps(self, run_id: str, node_id: str, iteration: int) -> list[StepRow]:
        """This step's attempts, first to last."""
        ...

    async def begin(self, row: StepRow) -> None:
        """Writes the attempt's row before the executor runs; RunCancelledError once the run is cancelled."""
        ...

    async def finish(
        self, row: StepRow, *, status: StepStatus, port: str | None, output: Any, error: str | None
    ) -> None: ...


class MemoryJournal:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, int, int], StepRow] = {}

    async def steps(self, run_id: str, node_id: str, iteration: int) -> list[StepRow]:
        return sorted(
            (r for (ru, n, i, _), r in self.rows.items() if (ru, n, i) == (run_id, node_id, iteration)),
            key=lambda r: r.attempt,
        )

    async def begin(self, row: StepRow) -> None:
        # Stamped as the store stamps it, so a deadline counted from the attempt's start reads the same here.
        stamped = row if row.started_at else replace(row, started_at=datetime.now(UTC).isoformat())
        self.rows[(row.run_id, row.node_id, row.iteration, row.attempt)] = stamped

    async def finish(
        self, row: StepRow, *, status: StepStatus, port: str | None, output: Any, error: str | None
    ) -> None:
        k = (row.run_id, row.node_id, row.iteration, row.attempt)
        self.rows[k] = replace(self.rows.get(k, row), status=status, port=port, output=output, error=error)
