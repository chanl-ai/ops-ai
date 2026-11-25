"""The step journal's contract: one row per node attempt, keyed by run, node, iteration and attempt. The wrapper
(compiler.py) reads it before running a node and writes it around each attempt; the SQL implementation is
store/steps.py, and `MemoryJournal` serves the engine's own tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast

from ops_service_kit.http import Json

# running: an attempt under way, or one whose process died (dangling). waiting: a review paused for a person.
# ok: recorded output, returned on any re-run. pinned: an output set before a test run. error: the attempt failed.
# abandoned: a dangling read or model attempt superseded by a new attempt. redriven: the failing attempt a Redrive set
# aside, kept with its port and output as history, so the step runs again instead of returning it.
StepStatus = Literal["running", "waiting", "ok", "pinned", "error", "abandoned", "redriven"]

# The ways a step leaves when it did not do its job: what a failure End names as the reason the run failed, and the
# recorded attempts a Redrive sets aside.
FAILING_PORTS = ("error", "refused", "unreadable", "timeout")

# Gateway codes for a call that never reached the outside system (tools-service executor.py transport_failure), and
# a 429 the system refused before acting: safe to send again.
NEVER_SENT = frozenset({"CONNECT_FAILED", "CONNECT_TIMEOUT", "POOL_TIMEOUT", "TLS_FAILED", "RATE_LIMITED"})

# Gateway refusals made before anything is sent: no address, account, sign-in, secret or egress for the call, or its
# own input refused (tools-service executor.py, auth and plugins/executor.py). A write that ends this way did not run.
REFUSED_BEFORE_SENDING = frozenset(
    {
        "CONNECTION_NOT_SET",
        "CONNECTION_MISSING",
        "CONNECTION_NOT_LINKED",
        "CONNECTION_OUT_OF_SCOPE",
        "CONNECTION_REVOKED",
        "AUTH_FAILED",
        "NOT_SIGNED_IN",
        "SIGN_IN_NOT_FOUND",
        "SECRET_MISSING",
        "SECRET_UNAVAILABLE",
        "EGRESS_DENIED",
        "PLUGIN_DISABLED",
        "INVALID_INPUT",
    }
)


def never_sent(error: Any) -> bool:
    return isinstance(error, dict) and cast(Json, error).get("code") in NEVER_SENT


def sent_and_unanswered(error: Any) -> bool:
    """Whether a gateway error says the call reached the outside system and no answer came back that says what it did:
    it timed out after connecting, broke off, or answered 5xx (tools-service executor.py transport_failure and
    status_failure). A write that ends this way may have happened, so a run's own pass fails it as uncertain."""
    if not isinstance(error, dict):
        return False
    e = cast(Json, error)
    code, status = e.get("code"), e.get("status")
    if code == "UPSTREAM_TIMEOUT":
        return True
    return code == "UPSTREAM_ERROR" and (status is None or (isinstance(status, int) and status >= 500))


# A plugin's request that failed, or a plugin that raised (plugins/executor.py): either can happen after a request went
# out. A run's own pass routes these to the step's error port; a Redrive reads them as may-have-run and never resends.
PLUGIN_MAY_HAVE_SENT = frozenset({"UPSTREAM_UNREACHABLE", "PLUGIN_FAILED"})


def definitely_not_done(error: Any) -> bool:
    """Whether a recorded gateway error proves the call did nothing: it never left (NEVER_SENT), the gateway refused it
    before sending (REFUSED_BEFORE_SENDING, or its own side), or the system answered with a 4xx refusal. Anything else,
    a plugin failure (PLUGIN_MAY_HAVE_SENT) or an unknown code included, may have run. Read only by a Redrive."""
    if not isinstance(error, dict) or sent_and_unanswered(error):
        return False
    e = cast(Json, error)
    code, status = e.get("code"), e.get("status")
    if never_sent(e) or code in REFUSED_BEFORE_SENDING or e.get("side") == "ours":
        return True
    if code in PLUGIN_MAY_HAVE_SENT:
        return False
    return isinstance(status, int) and 400 <= status < 500 and status != 408


def error_of(out: Any) -> Any:
    """The gateway's error inside a step's output: the error port wraps the tool's own `{"error": ...}` once more."""
    error: Any = cast(Json, out).get("error") if isinstance(out, dict) else None
    while isinstance(error, dict):
        layer = cast(Json, error)
        inner: Any = layer.get("error")
        if "code" in layer or not isinstance(inner, dict):
            break
        error = cast(Any, inner)
    return cast(Any, error)


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
