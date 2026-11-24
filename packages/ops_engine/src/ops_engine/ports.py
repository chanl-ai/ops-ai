"""Everything the engine reaches outside itself, named as docs/architecture/workflow-runner.md section 2 names them.
agents-service implements them with adapters; moving the engine to its own service means moving this package and
re-implementing the adapters, nothing else."""

from __future__ import annotations

from collections.abc import Generator, Mapping
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ops_agent_kernel.ports import KnowledgePort
from ops_service_kit.http import Json

Access = Literal["read", "write", "unknown"]
# What a write does when its gateway died after claiming it, so no record says whether it ran. `idempotent`: the
# system dedupes on the run-and-step key (`run:node:iteration`), so it is sent again. `checkable`: a read of the system
# (ToolPort's optional `read_back`) says whether it ran. `unsafe`: a person decides; the run pauses as Stuck.
WriteClass = Literal["idempotent", "checkable", "unsafe"]
WRITE_CLASSES: tuple[WriteClass, ...] = ("idempotent", "checkable", "unsafe")

# Marks an exception raised by a real outbound call: a tool, an app, a model or another service failing, which the
# error model reads as upstream and retryable (`tool_failed`). Anything a step raises without it is our own fault
# (`internal_error`), including a bug in a host's adapter, so an adapter marks only the call itself (`outside_call`).
OUTSIDE = "_ops_engine_outside"


class OutsideAnswerError(RuntimeError):
    """An outside system answered something the step cannot use (a failed extraction, a state it does not know): its
    failure, raised by the engine, so it reads as upstream like an error raised by the call itself."""

    _ops_engine_outside = True


@contextmanager
def outside_call() -> Generator[None]:
    """Wrap a port adapter's real outbound call (tools-service, an app, a model): whatever it raises is marked as the
    outside system failing and raised again unchanged, so callers still catch its own types and read its `code`."""
    try:
        yield
    except Exception as e:
        # An exception type without a __dict__ cannot carry the mark and reads as ours.
        with suppress(AttributeError, TypeError):
            setattr(e, OUTSIDE, True)
        raise


def is_outside(e: BaseException) -> bool:
    """Whether `e`, or an exception it was explicitly raised from, came from an outside call. Only `__cause__` is
    followed: a bug of ours inside an `except` block keeps the outside error as `__context__`, still ours."""
    seen: BaseException | None = e
    while seen is not None:
        if getattr(seen, OUTSIDE, False):
            return True
        seen = seen.__cause__
    return False


@dataclass(frozen=True)
class ToolResult:
    """What the gateway answered. `ok` False with `refused` is a policy refusal (the refused port); `ok` False without
    it is the operation's own error (the error port). Neither is retried: retrying is for a call that never got an
    answer, which the port raises as an exception instead."""

    ok: bool
    output: Any = None
    refused: bool = False
    reason: str | None = None
    # Only from find(): the gateway has the call and is still running it, so its outcome is not known yet.
    pending: bool = False
    # Only from find(): the gateway's claim expired without an answer, so the write may have run.
    lost: bool = False
    # The gateway refused the key as abandoned: the call never ran under it and never will.
    not_sent: bool = False


# Set while a step sends a call on the team's account in place of the person the run acts for ("Run as the
# team account"); the host's tool port then sends the call acting for nobody, which the gateway signs in with the team
# account where the app allows one. A context value, so no ToolPort implementation changes its signature.
AS_TEAM_ACCOUNT: ContextVar[bool] = ContextVar("ops_engine_as_team_account", default=False)
# Set while a step sends a call that names an account per app (app id to name); the host's tool port sends it over the
# run's own choice, and the gateway checks it. A context value for the same reason as AS_TEAM_ACCOUNT.
STEP_ACCOUNTS: ContextVar[Mapping[str, str] | None] = ContextVar("ops_engine_step_accounts", default=None)


class ToolPort(Protocol):
    async def call(
        self,
        operation: str,
        input: Json,
        key: str,
        generation: int | None,
        token: str | None,
    ) -> ToolResult:
        """One call through the tool gateway under `key` (run:node:iteration:attempt), fenced by `generation`, on
        the accounts the step names (STEP_ACCOUNTS) over the run's own."""
        ...

    async def access(self, operation: str) -> Access:
        """The operation's access class in the registry; "unknown" when it is not registered."""
        ...

    async def mint(self, run_id: str, call: Json, approval: Json) -> str | None:
        """An approval token for `call` from the approvals a review recorded (`approval`: step, tool, inputHash,
        approvers), made only for the call that is about to be sent; None when those approvals no longer stand."""
        ...

    async def find(self, key: str, operation: str) -> ToolResult | None:
        """The gateway's record of the write sent under `key`, for reconciling it after a crash; None when the gateway
        has none, in which case the key is abandoned there so a call still in flight cannot run later."""
        ...

    # Two optional methods, read with getattr so a port without them reads every write as `unsafe`:
    # `write_class(operation) -> WriteClass`, the class the operation declares, and `read_back(operation, input) ->
    # ToolResult | None` for a `checkable` one: the system's answer when the write ran, None when it did not.


class ExpressionPort(Protocol):
    async def evaluate(self, expressions: dict[str, str], values: Json) -> tuple[Json | None, str | None]:
        """Each formula's value by name and None, or None and why one failed: the tool gateway's sandbox evaluates
        them (POST /v1/expressions/evaluate). Raises when the gateway gives no answer, so the step is retried."""
        ...


class ReviewPort(Protocol):
    async def open(self, run_id: str, node_id: str, iteration: int, payload: Json) -> str:
        """Opens the review for this step, or finds the one already open (upsert on run, node, iteration); returns its
        id. The decision arrives later as a resume of the run."""
        ...

    async def own_decision(self, run_id: str, node_id: str, payload: Json) -> Json | None:
        """The decision of a step that approves a write when the person who started the run may approve it themselves
        (roles decide approvals): {decision, by, call, approval}, recorded as theirs. None to pause
        for a person as before."""
        ...


class TaskTypePort(Protocol):
    async def pin(self, type_id: str, version: int | None) -> int:
        """The published version of a task type a review opens with: the one named, or the newest when None. Raises
        when the type or that version is not published, so the step fails rather than opening a task with no screen."""
        ...


@dataclass(frozen=True)
class AgentRequest:
    agent_id: str
    # What the agent is asked: the step's prompt with its mapped input.
    message: str
    # Derived from run, node and iteration (run:node:iteration), so the turn's tool keys repeat on a re-run.
    turn_id: str
    output_schema: Json | None = None
    # The step's own settings: a model alias the agent allows, and a tool-call cap below the agent's.
    model_alias: str | None = None
    max_tool_calls: int | None = None


@dataclass(frozen=True)
class AgentResult:
    """A finished turn: `ok` with the validated `output` (or the text when no schema was asked). Not ok with
    `code` schema_error is the agent answering outside the schema, which the step routes to its error port; any other
    failure (no model, a refused call) is raised by the port instead, so the wrapper retries it."""

    ok: bool
    output: Any = None
    text: str = ""
    error: str | None = None
    code: str | None = None


class AgentPort(Protocol):
    async def turn(self, request: AgentRequest) -> AgentResult: ...


@dataclass(frozen=True)
class PromptRequest:
    """One model call with no saved agent (the AI steps): the step's own instructions, its text, the answer's JSON
    Schema and a model alias (the workspace's when None). No tools and no knowledge."""

    instructions: str
    message: str
    # run:node:iteration, as an agent step's, so a re-run repeats the call's ledger key.
    turn_id: str
    output_schema: Json
    model_alias: str | None = None
    # The run the step is in, so the host applies the run's team settings (masking personal data).
    run_id: str | None = None


class PromptPort(Protocol):
    async def prompt(self, request: PromptRequest) -> AgentResult:
        """The answer as an AgentResult: ok with the output, or not ok with code schema_error or no_output, which the
        step takes to its error port. Anything else (no model, models-service down) is raised, so the step retries."""
        ...


class FileDataPort(Protocol):
    async def set_data(self, run_id: str, file_id: str, data: Json) -> Json:
        """Records on the file what was read from it, as the run's team: files-service's
        PUT /v1/files/{id}/data. Another team's file is not found; files-service down is raised, so the wrapper
        retries."""
        ...


class DocumentsPort(Protocol):
    async def extract(self, run_id: str, file_id: str, request: Json, *, key: str) -> Json:
        """documents-service's extraction of the file, as the run's team, finished: `{status, outcome,
        ...}` with status done, unreadable or failed and, once done, the scored answer. `request` is {fields, many,
        ocr, reviewBelow}; `key` (run:node:iteration) is the Idempotency-Key, so a retried step reads the same
        extraction. Another team's or tenant's file is not found; documents-service down is raised, so the wrapper
        retries."""
        ...

    async def reading(self, run_id: str, file_id: str, *, ocr: str, ask: bool) -> Json:
        """The file's one shared reading with OCR mode `ocr` (auto or off), as the run's team, never waited for: done
        with every page, failed with its error, queued or reading (reported by reading.finished or reading.failed when
        it ends), or none. `ask` asks for it (POST /v1/documents/readings), which reads a failed one again; otherwise it
        is read as it is (GET). Another team's or tenant's file is not found; documents-service down is raised, so the
        wrapper retries."""
        ...

    async def purge(self, run_id: str, file_id: str) -> Json:
        """Removes what documents-service read from a deleted file, as the run's team: {extractions, samples}."""
        ...

    async def correct(self, run_id: str, extraction_id: str, corrections: list[Json], *, entered_by: str) -> Json:
        """Saves what a person typed into a read ([{field, record?, value}]) on its extraction, as the run's team,
        recorded as `entered_by`, with the whole read checked. A value documents-service refuses (one its field's type
        cannot hold) is `{"refused": {code, message}}`; documents-service down is raised, so the wrapper retries."""
        ...


class DocumentTypesPort(Protocol):
    async def fields(self, run_id: str, type_id: str, version: int | None) -> list[Json]:
        """A document type's fields at a version (the newest when None), as the run's team reads them from
        documents-service: what Extract from text asks for when a step names a type."""
        ...


class TimerPort(Protocol):
    async def set(self, run_id: str, node_id: str, key: str, due_in_seconds: float) -> None: ...

    async def cancel(self, run_id: str, node_id: str, key: str) -> None: ...


@dataclass(frozen=True)
class StartedRun:
    run_id: str
    # False when the key had started the run already: a retried or re-run step finds its child, never a second one.
    created: bool


class RunRefusedError(Exception):
    """The host will not start the child: the workflow is not live, is paused, is not the team's, or the chain of runs
    started by runs is too deep. The step takes its error port with `code` and the message."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class RunPort(Protocol):
    async def start(self, parent_run_id: str, workflow: str, input: Json, key: str) -> StartedRun:
        """Starts `workflow` as a child of `parent_run_id`, in the parent's team and mode, once for `key`. Raises
        RunRefusedError when the host refuses it."""
        ...

    async def children(self, parent_run_id: str, key_prefix: str, *, outputs: bool = False) -> list[Json]:
        """The children `parent_run_id` started under keys beginning `key_prefix` (`<run>:<node>:<iteration>:`), in one
        read: `{index, runId, status, outcome, output}` each, ordered by the item index the key ends with;
        `output` is None unless `outputs`."""
        ...


@dataclass(frozen=True)
class OpenedCase:
    case_id: str
    # False when the key had opened the case already: a retried or re-run step finds it, never opens a second.
    created: bool


class CaseNotFoundError(Exception):
    """No case with that id in the run's team: the step takes its error port."""


class CaseTypeNotFoundError(Exception):
    """The case type an Open case step names has no published version: the step takes its error port."""


class CasePort(Protocol):
    """The host's cases: a case opens in the run's team, and a run joins one of that team's cases."""

    async def open(self, run_id: str, fields: Json, key: str) -> OpenedCase:
        """Opens a case in the run's team with `fields` (subject, priority, customerId, customerName, assignee,
        `caseType`, and `fields`, the case's own values by name), once for `key`; the run is its first timeline entry.
        A named case type's newest published version is pinned on the case; raises CaseTypeNotFoundError for one that
        has none."""
        ...

    async def add(
        self,
        run_id: str,
        case_id: str,
        note: str | None,
        fields: Json | None = None,
        *,
        status: str | None = None,
        key: str | None = None,
    ) -> None:
        """Adds the run to the case's timeline, `fields` to the case's own values and moves it to `status` (never to or
        from closed, which is a person's); a later step of the same run adds its `note` once for its `key`. Raises
        CaseNotFoundError for a case outside the run's team."""
        ...


class StepHooks(Protocol):
    async def after_step(self, run_id: str, node_id: str, status: str) -> None:
        """Called once a step's journal row is finished, before the node returns to LangGraph."""
        ...


class NoHooks:
    async def after_step(self, run_id: str, node_id: str, status: str) -> None:
        return None


@dataclass(frozen=True)
class Faults:
    """Fault injection for the use cases that prove crash recovery; the host sets it only from settings refused outside
    dev and test. `ignore_recorded` re-runs every step instead of returning its recorded output, which is the failure
    the recovery checks must catch."""

    ignore_recorded: bool = False


@dataclass
class EnginePorts:
    """Slice 1 runs tools and reviews; the other ports are declared for the types that follow and stay None."""

    tools: ToolPort
    reviews: ReviewPort
    agents: AgentPort | None = None
    documents: DocumentsPort | None = None
    file_data: FileDataPort | None = None
    knowledge: KnowledgePort | None = None
    timers: TimerPort | None = None
    runs: RunPort | None = None
    cases: CasePort | None = None
    # Calculate steps' formulas, evaluated in the tool gateway's sandbox.
    expressions: ExpressionPort | None = None
    # Review steps that name a task type pin its version here; without it the version stays as the step names it.
    task_types: TaskTypePort | None = None
    # AI steps (classify, summarise, extract from text, draft) make one model call each through it.
    prompts: PromptPort | None = None
    document_types: DocumentTypesPort | None = None
    hooks: StepHooks = field(default_factory=NoHooks)
    faults: Faults = field(default_factory=Faults)


# ── What the worker loop needs from its host ──


class LeaseBusyError(Exception):
    """Another owner holds the run's thread lease and it has not expired."""


class LeasePort(Protocol):
    """The host's per-thread lease with its fencing generation (ADR-0016)."""

    ttl: float

    async def acquire(self, thread_id: str, run_id: str) -> int:
        """The new generation; raises LeaseBusyError while a live owner holds it."""
        ...

    async def heartbeat(self, thread_id: str, run_id: str) -> bool: ...

    async def release(self, thread_id: str, run_id: str) -> None: ...


class EventPort(Protocol):
    async def append(
        self, run_id: str, team_id: str, type_: str, node: str | None, data: Any, *, generation: int | None = None
    ) -> None:
        """Appends an event to the run's thread event log at its next seq, so a client re-attaches with after=seq.
        With `generation`, refused (LeaseSupersededError) once the run's lease has moved past it."""
        ...
