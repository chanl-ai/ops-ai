"""Everything the engine reaches outside itself, named as docs/architecture/workflow-runner.md section 2 names them.
agents-service implements them with adapters; moving the engine to its own service means moving this package and
re-implementing the adapters, nothing else."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ops_agent_kernel.ports import KnowledgePort

Access = Literal["read", "write", "unknown"]


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
    # Only from find(): the gateway's claim expired without an answer, so the write may have run (c-561).
    lost: bool = False
    # The gateway refused the key as abandoned: the call never ran under it and never will (c-561).
    not_sent: bool = False


class ToolPort(Protocol):
    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        """One call through the tool gateway under `key` (run:node:iteration:attempt), fenced by `generation`."""
        ...

    async def access(self, operation: str) -> Access:
        """The operation's access class in the registry; "unknown" when it is not registered."""
        ...

    async def mint(self, run_id: str, call: dict[str, Any], approval: dict[str, Any]) -> str | None:
        """An approval token for `call` from the approvals a review recorded (`approval`: step, tool, inputHash,
        approvers), made only for the call that is about to be sent; None when those approvals no longer stand."""
        ...

    async def find(self, key: str, operation: str) -> ToolResult | None:
        """The gateway's record of the write sent under `key`, for reconciling it after a crash; None when the gateway
        has none, in which case the key is abandoned there so a call still in flight cannot run later."""
        ...


class ExpressionPort(Protocol):
    async def evaluate(
        self, expressions: dict[str, str], values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Each formula's value by name and None, or None and why one failed: the tool gateway's sandbox evaluates
        them (POST /v1/expressions/evaluate). Raises when the gateway gives no answer, so the step is retried."""
        ...


class ReviewPort(Protocol):
    async def open(self, run_id: str, node_id: str, iteration: int, payload: dict[str, Any]) -> str:
        """Opens the review for this step, or finds the one already open (upsert on run, node, iteration); returns its
        id. The decision arrives later as a resume of the run."""
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
    output_schema: dict[str, Any] | None = None
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
    """One model call with no saved agent (c-298's AI steps): the step's own instructions, its text, the answer's JSON
    Schema and a model alias (the workspace's when None). No tools and no knowledge."""

    instructions: str
    message: str
    # run:node:iteration, as an agent step's, so a re-run repeats the call's ledger key.
    turn_id: str
    output_schema: dict[str, Any]
    model_alias: str | None = None
    # The run the step is in, so the host applies the run's team settings (masking personal data, c-321).
    run_id: str | None = None


class PromptPort(Protocol):
    async def prompt(self, request: PromptRequest) -> AgentResult:
        """The answer as an AgentResult: ok with the output, or not ok with code schema_error or no_output, which the
        step takes to its error port. Anything else (no model, models-service down) is raised, so the step retries."""
        ...


class FileDataPort(Protocol):
    async def set_data(self, run_id: str, file_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Records on the file what was read from it (c-250), as the run's team: files-service's
        PUT /v1/files/{id}/data. Another team's file is not found; files-service down is raised, so the wrapper
        retries."""
        ...


class DocumentsPort(Protocol):
    async def extract(self, run_id: str, file_id: str, request: dict[str, Any], *, key: str) -> dict[str, Any]:
        """documents-service's extraction of the file (c-235, c-256), as the run's team, finished: `{status, outcome,
        ...}` with status done, unreadable or failed and, once done, the scored answer. `request` is {fields, many,
        ocr, reviewBelow}; `key` (run:node:iteration) is the Idempotency-Key, so a retried step reads the same
        extraction. Another team's or tenant's file is not found; documents-service down is raised, so the wrapper
        retries."""
        ...

    async def purge(self, run_id: str, file_id: str) -> dict[str, Any]:
        """Removes what documents-service read from a deleted file, as the run's team: {extractions, samples}."""
        ...


class DocumentTypesPort(Protocol):
    async def fields(self, run_id: str, type_id: str, version: int | None) -> list[dict[str, Any]]:
        """A document type's fields at a version (the newest when None), as the run's team reads them from
        documents-service: what Extract from text asks for when a step names a type (c-298)."""
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
    async def start(self, parent_run_id: str, workflow: str, input: dict[str, Any], key: str) -> StartedRun:
        """Starts `workflow` as a child of `parent_run_id`, in the parent's team and mode, once for `key`. Raises
        RunRefusedError when the host refuses it."""
        ...

    async def children(self, parent_run_id: str, key_prefix: str, *, outputs: bool = False) -> list[dict[str, Any]]:
        """The children `parent_run_id` started under keys beginning `key_prefix` (`<run>:<node>:<iteration>:`), in one
        read: `{index, runId, status, outcome, output}` each, ordered by the item index the key ends with (c-263);
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
    """The host's cases (c-219): a case opens in the run's team, and a run joins one of that team's cases."""

    async def open(self, run_id: str, fields: dict[str, Any], key: str) -> OpenedCase:
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
        fields: dict[str, Any] | None = None,
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
