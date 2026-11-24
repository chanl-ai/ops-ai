"""The node type registry: what each kind of node is, read by the editor, the validator and the runner alike.

A type is a definition the platform ships (docs/design/workflows/workflow-nodes.md): a namespaced id and an
integer version, a group, input and output ports with their connection type, parameters as JSON Schema, the form the
console generates for them (`ui`), an effects class, a retry default and the executor that runs it. A workflow's node
is an instance that pins one type version.

Retry follows the effects class (docs/architecture/workflow-runner.md section 4): a write gets one attempt and a
reconciliation read, never a second send.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from ops_service_kit.http import Json, JsonValue
from ops_store.retry import jittered

from .starts import ONLY_FROM_WORKFLOWS, StartSpec, only_from_workflows, trigger_node
from .store.definitions import ListColumns, watched_mailbox

Effects = Literal["none", "model", "read", "write", "human"]
Group = Literal["trigger", "data", "ai", "action", "flow", "human"]
ConnectionType = Literal["main", "model", "tool", "knowledge", "memory"]

# The form a type's settings are edited in: a closed set of widgets the console renders, and a closed set of option
# sources the platform serves (GET /v1/workflows/option-sources; `steps` is the definition being edited). A pack
# ships data only, so it can neither add a widget nor run code to load options.
# `account` picks, for the app the step's operation belongs to, one of the team's accounts (tools-service lists them).
WIDGETS = frozenset(
    {
        "text",
        "textarea",
        "number",
        "select",
        "switch",
        "mapping",
        "mappings",
        "list",
        "options",
        "categories",
        "source",
        "json",
        "account",
    }
)
OPTION_SOURCES = frozenset({"agents", "tools", "knowledge", "workflows", "steps", "mailboxes"})


@dataclass(frozen=True)
class Port:
    name: str
    connection: ConnectionType = "main"
    label: str | None = None

    def view(self) -> Json:
        return {"name": self.name, "connection": self.connection, "label": self.label or self.name.capitalize()}


@dataclass(frozen=True)
class Retry:
    """`attempts` counts the first; `backoff` is the wait before the second and the cap, in seconds. `waits`, when
    given, is the wait before each retry in turn instead (the last repeats). Every wait is jittered (`jittered`).
    `total_seconds` bounds the step's attempts and waits together: whichever of it and `attempts` runs out first ends
    the retries."""

    attempts: int
    backoff: tuple[float, float] = (0.0, 0.0)
    waits: tuple[float, ...] = ()
    total_seconds: float = 900.0

    def span(self, attempt: int) -> float:
        """The longest wait before `attempt` (2 for the first retry)."""
        if self.waits:
            return self.waits[min(max(0, attempt - 2), len(self.waits) - 1)]
        base, cap = self.backoff
        return min(cap, base * 2 ** max(0, attempt - 2)) if base else 0.0

    def wait(self, attempt: int, retry_after: float | None = None) -> float:
        """Seconds to wait before `attempt`: jittered over its span, never shorter than `retry_after`."""
        return jittered(self.span(attempt), retry_after)

    def view(self) -> Json:
        backoff: list[JsonValue] = list(self.waits) if self.waits else list(self.backoff)
        return {"attempts": self.attempts, "backoffSeconds": backoff}


# An outage's backoff: 5 s, then 30 s, so a service restart or a short blip is ridden out.
OUTAGE_WAITS = (5.0, 30.0)


# Section 4's table. Human steps are not retried: a re-run finds the same review.
RETRY_BY_EFFECTS: dict[Effects, Retry] = {
    "none": Retry(3),
    "read": Retry(3, waits=OUTAGE_WAITS),
    "model": Retry(2),
    # A write is sent again only when the gateway proves it never ran it, each time under a new attempt key.
    "write": Retry(3, waits=OUTAGE_WAITS),
    "human": Retry(1),
}


# In optional_outputs and outputs_unless: any value set (not None, empty or false), as `timeoutHours` given at all.
SET = object()


def _port_rule(param: str, value: Any, port: str) -> Json:
    return {"parameter": param, "value": "*" if value is SET else value, "port": port}


def _holds(parameters: Mapping[str, JsonValue] | None, param: str, value: Any) -> bool:
    found = (parameters or {}).get(param)
    return found not in (None, "", False) if value is SET else found == value


@dataclass(frozen=True)
class NodeType:
    id: str
    version: int
    group: Group
    label: str
    description: str
    executor: str
    effects: Effects
    inputs: tuple[Port, ...] = ()
    outputs: tuple[Port, ...] = ()
    parameters: Mapping[str, JsonValue] = field(default_factory=lambda: {"type": "object", "properties": {}})
    # Outputs derived from a parameter: one port per entry of that list parameter (a review's options).
    outputs_from: str | None = None
    # (parameter, value, port): an extra out port the instance has while `parameter` is `value`, e.g. a review's
    # `timeout` port when it expires.
    optional_outputs: tuple[tuple[str, Any, str], ...] = ()
    # (parameter, value, port): a declared out port the instance drops while `parameter` is `value`, e.g. Run
    # workflow's `started` while it waits for its children. A value of SET matches any value set.
    outputs_unless: tuple[tuple[str, Any, str], ...] = ()
    # Out ports every instance has besides the ones `outputs_from` lists, such as a Switch's otherwise.
    extra_outputs: tuple[str, ...] = ()
    retry: Retry | None = None
    # Runs once, when no other step of the run can still run (a LangGraph deferred node): a Join waits for every branch
    # that will arrive and never for one routed away.
    deferred: bool = False
    # A write keyed by its step, so a retry repeats nothing (starting a child run): retried by `retry`, never reconciled
    # through the tool gateway, which does not see it.
    idempotent: bool = False
    # Per-attempt limit on the executor; a node parameter `timeoutSeconds` overrides it.
    timeout_seconds: float = 30.0
    # The generated form: {"order": [...], "fields": {name: {"label", "widget", "help"?, "placeholder"?, "source"?,
    # "item"?}}}. `item` is the same shape for the objects of a `list`. Checked against `parameters` on register.
    ui: Mapping[str, JsonValue] = field(default_factory=lambda: {"order": [], "fields": {}})
    # How a person starts a workflow this trigger begins by hand (starts.py); None for a trigger only its source starts.
    start: StartSpec | None = None
    # What the console's step sheet tells a person building a workflow: one plain sentence, then how it works, fails,
    # waits and what it hands on. `description` stays the precise text models and docs read.
    summary: str = ""
    how: str = ""
    # What the sheet's "When it fails" says about retries and the time limit for a step that waits rather than works:
    # a review waits for a person, a Wait for the time it is given. Empty: the sheet words the type's retry policy and
    # per-attempt limit.
    tries: str = ""
    limit: str = ""
    # A trigger a saved schedule may sit on: the schedule clock starts its runs with `dueAt` as the only input.
    schedulable: bool = False

    @property
    def key(self) -> tuple[str, int]:
        return (self.id, self.version)

    def retry_policy(self) -> Retry:
        return self.retry or RETRY_BY_EFFECTS[self.effects]

    def output_ports(self, parameters: Mapping[str, JsonValue] | None = None) -> list[str]:
        """The instance's out ports: the declared ones, or one per entry of `outputs_from` when the instance sets it."""
        ports = [p.name for p in self.outputs]
        if self.outputs_from and parameters is not None:
            raw = parameters.get(self.outputs_from)
            if isinstance(raw, list) and raw:
                ports = [option_name(o) for o in cast(list[Any], raw)]
        extra = [port for param, value, port in self.optional_outputs if _holds(parameters, param, value)]
        dropped = {port for param, value, port in self.outputs_unless if _holds(parameters, param, value)}
        return [p for p in ports + [p for p in [*self.extra_outputs, *extra] if p not in ports] if p not in dropped]

    def fails(self) -> str:
        """What a failure does once the step's own retries are used, as the compiler's Wrapper and the worker do it: a
        step with an error port goes on by it; otherwise a cause that can pass retries the run, then pauses it as
        Stuck (MAX_PASSES), and any other cause fails the run."""
        on_error = "It goes on by the Error path, so the steps you join to it decide what happens next."
        stops = (
            "If the cause can pass, such as an app not answering, the run is tried again later and then waits as "
            "Stuck for your team to retry it. Otherwise the run stops as Failed."
        )
        if "error" in self.output_ports():
            return on_error
        if any(port == "error" for _, _, port in self.optional_outputs):
            return (
                f"When its settings give it an Error path, it goes on by it. Without one: {stops[0].lower()}{stops[1:]}"
            )
        return stops

    def view(self) -> Json:
        return {
            "id": self.id,
            "version": self.version,
            "group": self.group,
            "label": self.label,
            "description": self.description,
            "summary": self.summary,
            "how": self.how,
            "tries": self.tries,
            "limit": self.limit,
            "fails": self.fails(),
            "inputs": [p.view() for p in self.inputs],
            "outputs": [p.view() for p in self.outputs],
            "outputsFrom": self.outputs_from,
            "extraOutputs": list(self.extra_outputs),
            # So an editor draws the extra port while the instance's parameter holds the value, as output_ports does.
            "optionalOutputs": [_port_rule(a, v, p) for a, v, p in self.optional_outputs],
            # A declared port the instance drops while `parameter` is `value` ("*": any value set).
            "outputsUnless": [_port_rule(a, v, p) for a, v, p in self.outputs_unless],
            "parameters": dict(self.parameters),
            "effects": self.effects,
            "retry": self.retry_policy().view(),
            "executor": self.executor,
            "timeoutSeconds": self.timeout_seconds,
            "ui": dict(self.ui),
        }


def option_name(option: Any) -> str:
    """An option is a name, or an object with a `name`."""
    if isinstance(option, dict):
        return str(cast(Json, option).get("name") or "")
    return str(option)


def ui_problems(schema: Mapping[str, JsonValue], ui: Mapping[str, JsonValue], at: str = "") -> list[str]:
    """What is wrong with a form against the parameters it edits: a field that is no parameter, a parameter with no
    field, an unknown widget or option source, a `list` with no item form. Empty when the form is sound."""
    props = cast(Mapping[str, JsonValue], schema.get("properties") or {})
    fields = cast(Mapping[str, JsonValue], ui.get("fields") or {})
    order = list(cast(list[str], ui.get("order") or []))
    out: list[str] = []
    if sorted(order) != sorted(fields):
        out.append(f"{at}order {order} does not list exactly the fields {sorted(fields)}")
    out += [f"{at}{name} has no form field" for name in props if name not in fields]
    for name, spec in fields.items():
        f = cast(Mapping[str, JsonValue], spec)
        where = f"{at}{name}: "
        if name not in props:
            out.append(f"{where}not a parameter")
            continue
        widget = f.get("widget")
        if widget not in WIDGETS:
            out.append(f"{where}unknown widget {widget!r}")
        if not f.get("label"):
            out.append(f"{where}no label")
        if widget == "source" and f.get("source") not in OPTION_SOURCES:
            out.append(f"{where}unknown option source {f.get('source')!r}")
        if widget == "list":
            items = cast(Mapping[str, JsonValue], cast(Mapping[str, JsonValue], props[name]).get("items") or {})
            item = f.get("item")
            if not isinstance(item, Mapping):
                out.append(f"{where}a list needs an item form")
            else:
                out += ui_problems(items, cast(Mapping[str, JsonValue], item), f"{at}{name}[].")
    return out


class UnknownType(KeyError):
    pass


class TypeRegistry:
    def __init__(self, types: Iterable[NodeType] = ()) -> None:
        self._types: dict[tuple[str, int], NodeType] = {}
        for t in types:
            self.register(t)

    def register(self, node_type: NodeType) -> None:
        if node_type.key in self._types:
            raise ValueError(f"{node_type.id} version {node_type.version} is already registered")
        # A form that names a setting the type does not have, or misses one, would let the editor offer a setting the
        # runner does not understand; the type is refused instead.
        if problems := ui_problems(node_type.parameters, node_type.ui):
            raise ValueError(f"{node_type.id} version {node_type.version} has an unsound form: {problems}")
        self._types[node_type.key] = node_type

    def find(self, type_id: str, version: int) -> NodeType | None:
        return self._types.get((type_id, version))

    def get(self, type_id: str, version: int) -> NodeType:
        found = self.find(type_id, version)
        if found is None:
            raise UnknownType(f"{type_id} version {version}")
        return found

    def versions(self, type_id: str) -> list[int]:
        return sorted(v for i, v in self._types if i == type_id)

    def all(self) -> list[NodeType]:
        return [self._types[k] for k in sorted(self._types)]


MAIN_IN = (Port("in"),)
# A field that names what the step acts on (an operation, an agent, another step) is a literal: resolve() would read a
# `$.` string from the run, so the input could choose what a reviewed workflow calls.
_NOT_A_PATH: Json = {
    "not": {"pattern": r"^\$\."},
    "x-problem": "must be typed or chosen here, not picked from another step",
}
CASE_PRIORITIES = ("low", "normal", "high", "urgent")
END_RESULTS = ("succeeded", "failed")


def _titled(*choices: tuple[str, str], **extra: JsonValue) -> Json:
    """A setting with a closed set of values, each with the words a form shows for it: `enum` keeps the schema check,
    `oneOf` carries the titles the console lists, so no code word reaches a builder."""
    return {"enum": [v for v, _ in choices], "oneOf": [{"const": v, "title": t} for v, t in choices], **extra}


_OPERATORS = (
    ("eq", "Equal to"),
    ("ne", "Not equal to"),
    ("gt", "Greater than"),
    ("gte", "At least"),
    ("lt", "Less than"),
    ("lte", "At most"),
    ("contains", "Contains"),
    ("exists", "Has a value"),
    ("empty", "Is empty"),
)
_COMBINE = (("all", "All of these"), ("any", "Any of these"))
_FIELD_TYPES = (("text", "Text"), ("number", "Number"), ("money", "Money"), ("date", "Date"))
_TIMEOUT_WAYS = (("error", "Take the Error way out"), ("port", "Take a Timeout way out"))


_MAPPING = (
    "A value, or a path into the run: `$.input.<field>` or `$.nodes.<node id>.out.<field>`; in a text, paths in "
    "braces are filled in: `Levy notice: {$.input.record.name}`"
)
_CONDITION: Json = {
    "type": "object",
    "required": ["left", "op"],
    "properties": {
        "left": {"description": _MAPPING},
        "op": _titled(*_OPERATORS),
        "right": {"description": _MAPPING},
    },
}


# A setting that may also be a path into the run, resolved when the step runs.
_A_PATH: Json = {"type": "string", "pattern": "^\\$\\."}


def _f(label: str, widget: str, help: str | None = None, **extra: JsonValue) -> Json:
    return {"label": label, "widget": widget, **({"help": help} if help else {}), **extra}


def _form(*fields: tuple[str, Json]) -> Json:
    return {"order": [n for n, _ in fields], "fields": dict(fields)}


_MATCH_RULE: Json = {
    "type": "object",
    "additionalProperties": False,
    "required": ["left", "op", "right"],
    "properties": {
        "left": {"type": "string", "minLength": 1, "description": "The record's field", **_NOT_A_PATH},
        "op": _titled(("equals", "Equals"), ("overlaps", "Overlaps")),
        "right": {"type": "string", "minLength": 1, "description": "The candidate's field", **_NOT_A_PATH},
        "minLength": {"type": "integer", "minimum": 1, "description": "Overlaps: the shorter value's least length"},
    },
}
_MATCH_RULE_FORM = _form(
    ("left", _f("Record field", "text")),
    ("op", _f("Is", "select")),
    ("right", _f("Candidate field", "text")),
    ("minLength", _f("Least length", "number")),
)
# A service event's name: dotted lower-case words, the subject first, e.g. tool_access.requested.
EVENT_NAME = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"
# A Start workflow step's limits: how many children one step may start, and its default.
MAX_ITEMS, DEFAULT_MAX_ITEMS = 500, 50
_TIMEOUT = ("timeoutSeconds", _f("Time limit (seconds)", "number", "Per attempt; the type's default when empty"))

# What every AI step takes: the text it reads, extra instructions and a model alias. Each step adds its own.
_AI_COMMON: Json = {
    "text": {"description": "What the model reads: " + _MAPPING},
    "instructions": {"type": "string", "description": "Anything the model should know or do besides the step's job"},
    "model": {
        "type": "string",
        "minLength": 1,
        **_NOT_A_PATH,
        "description": "A model alias for this step; the workspace's when empty",
    },
    "timeoutSeconds": {"type": "number", "exclusiveMinimum": 0},
}
_AI_FORM = (
    ("text", _f("Text", "mapping", "The text the model reads; pick a field or type it")),
    ("instructions", _f("Instructions", "textarea", "Anything the model should know or do besides the step's job")),
    ("model", _f("Model", "text", "The model this step uses; empty uses the workspace's")),
)


def _ai_step(
    type_id: str,
    label: str,
    description: str,
    own: Json,
    form: tuple[tuple[str, Json], ...],
    *,
    required: tuple[str, ...] = (),
    outputs: tuple[Port, ...] = (Port("ok"), Port("error")),
    outputs_from: str | None = None,
    extra_outputs: tuple[str, ...] = (),
    summary: str = "",
    how: str = "",
) -> NodeType:
    """An AI step: one model call with no tools through EnginePorts.prompts (executor ai.prompt); ai_steps.JOBS holds
    what its answer looks like and which port it leaves by."""
    return NodeType(
        id=type_id,
        version=1,
        group="ai",
        label=label,
        summary=summary,
        how=how,
        description=description,
        executor="ai.prompt",
        effects="model",
        inputs=MAIN_IN,
        outputs=outputs,
        outputs_from=outputs_from,
        extra_outputs=extra_outputs,
        parameters={"type": "object", "required": ["text", *required], "properties": {**_AI_COMMON, **own}},
        timeout_seconds=120.0,
        ui=_form(_AI_FORM[0], *form, *_AI_FORM[1:], _TIMEOUT),
    )


# A test email's form: what the mailbox path reads from a message. The adapter (agents-service `run_starts.py`) turns it
# into the message the listener would read, attachments included.
TEST_EMAIL_FORM: Mapping[str, JsonValue] = {
    "type": "object",
    "required": ["from"],
    "properties": {
        "from": {"type": "string", "format": "email", "title": "From", "examples": ["clerk@county-court.example"]},
        "subject": {"type": "string", "title": "Subject", "examples": ["Notice of levy, case 2026-CV-1182"]},
        "body": {
            "type": "string",
            "title": "Body",
            "x-widget": "textarea",
            "examples": ["Please find the notice attached."],
        },
        "attachments": {
            "type": "array",
            "title": "Attachments",
            "description": "Upload files or pick ones already in Files; each reaches the workflow as a mailbox "
            "attachment would.",
            "items": {
                "type": "object",
                "format": "file",
                "properties": {"fileId": {"type": "string"}, "name": {"type": "string"}},
                "required": ["fileId"],
            },
        },
    },
}


BASIC_TYPES: tuple[NodeType, ...] = (
    NodeType(
        id="ops.trigger.request",
        version=1,
        group="trigger",
        label="Request",
        summary=(
            "Starts the workflow when another app, another workflow or a person starts it with the details it needs."
        ),
        how=(
            "The caller must be signed in, and what they send becomes the workflow's input. If you set an input form, "
            "a start that does not fit it is refused. The first step can read everything the caller sent."
        ),
        description="Starts a run from an authenticated API call or a system event; the run's input is the payload.",
        executor="trigger.payload",
        effects="none",
        outputs=(Port("payload"),),
        parameters={
            "type": "object",
            "properties": {
                "inputSchema": {"type": "object", "description": "JSON Schema the payload must match"},
                ONLY_FROM_WORKFLOWS: {
                    "type": "boolean",
                    "description": "Other workflows start it; Start run and Files do not offer it",
                },
            },
        },
        ui=_form(
            ("inputSchema", _f("Input form", "json", "The fields a start must send; empty takes any")),
            (
                ONLY_FROM_WORKFLOWS,
                _f("Only other workflows start this", "switch", "Start run and Files leave it out of their lists"),
            ),
        ),
        start=StartSpec(kind="form", title="Start a run", action="Start run", via="form", form_parameter="inputSchema"),
    ),
    NodeType(
        id="ops.trigger.email",
        version=1,
        group="trigger",
        label="Email received",
        summary="Starts the workflow when a new email arrives in a mailbox you choose.",
        how=(
            "It watches one folder of the mailbox and starts only for emails that match your filters. Each attachment "
            "is saved to Files first, so later steps can read it. Past the daily cap, an email is noted on Activity "
            "and starts nothing. The next step gets the sender, subject, body and attachments."
        ),
        description=(
            "Starts a run when an email arrives in a watched mailbox folder and matches the filters; the run's input "
            "is the email, with each attachment stored in Files first."
        ),
        executor="trigger.payload",
        effects="none",
        outputs=(Port("payload"),),
        parameters={
            "type": "object",
            "properties": {
                "mailbox": {"type": "string", "description": "A mailbox the team may watch; empty watches none"},
                "folder": {"type": "string", "default": "inbox", "description": "inbox, or a folder name"},
                "fromContains": {"type": "string", "description": "Only mail whose sender contains this"},
                "subjectContains": {"type": "string", "description": "Only mail whose subject contains this"},
                "hasAttachment": {"type": "boolean", "description": "Only mail with at least one attachment"},
                "dailyCap": {"type": "integer", "minimum": 1, "description": "Most runs to start in a UTC day"},
            },
        },
        ui=_form(
            (
                "mailbox",
                _f(
                    "Mailbox",
                    "source",
                    "A team mailbox an admin set up for workflows; empty reads no mail, and Start run still sends it "
                    "a test email",
                    source="mailboxes",
                ),
            ),
            ("folder", _f("Folder", "text", "inbox, or the name of another folder", placeholder="inbox")),
            ("fromContains", _f("From contains", "text", "Empty takes mail from anyone", placeholder="@court.example")),
            ("subjectContains", _f("Subject contains", "text", "Empty takes any subject")),
            ("hasAttachment", _f("Has an attachment", "switch", "Skip mail with no attachment")),
            (
                "dailyCap",
                _f(
                    "Daily cap",
                    "number",
                    "Most runs a day; mail past it is recorded on Activity, not run. Empty: no cap",
                ),
            ),
        ),
        start=StartSpec(
            kind="email", title="Send a test email", action="Send test email", via="test email", form=TEST_EMAIL_FORM
        ),
    ),
    NodeType(
        id="ops.trigger.event",
        version=1,
        group="trigger",
        label="Service event",
        summary="Starts a system workflow when something happens in the platform, such as a file being deleted.",
        how=(
            "Only workflows the platform maintains start this way. The details of what happened become the workflow's "
            "input. If you set an input form, the same form appears when someone starts the workflow by hand."
        ),
        description=(
            "Starts a run when a service reports an event, such as a file deleted or a tool access request; the run's "
            "input is the event's payload. Only a system workflow, which the platform maintains, is started by one. "
            "An input schema, when set, is also the form Start run shows."
        ),
        executor="trigger.payload",
        effects="none",
        outputs=(Port("payload"),),
        parameters={
            "type": "object",
            "properties": {
                "event": {
                    "type": "string",
                    "pattern": EVENT_NAME,
                    "x-problem": "must be lowercase words joined by dots, such as file.deleted",
                    "description": "The event's name, such as file.deleted",
                },
                "inputSchema": {
                    "type": "object",
                    "description": "JSON Schema Start run shows; empty means only the event starts the workflow",
                },
            },
            "required": ["event"],
        },
        ui=_form(
            ("event", _f("Event", "text", "The event's name, such as file.deleted", placeholder="file.deleted")),
            (
                "inputSchema",
                _f("Input form", "json", "The fields Start run asks for; empty means only the event starts it"),
            ),
        ),
        start=StartSpec(
            kind="form",
            title="Start a run",
            action="Start run",
            via="form",
            form_parameter="inputSchema",
            when_schema=True,
        ),
    ),
    NodeType(
        id="ops.trigger.schedule",
        version=1,
        group="trigger",
        label="Schedule",
        summary="Starts the workflow when its scheduled time comes.",
        how=(
            "When the clock reaches the due time, the workflow starts with the details saved with the schedule. A "
            "scheduled start with the same name never runs twice, even if it fires again."
        ),
        description="Starts a run when the platform clock reaches the due time. The same key fires once.",
        executor="trigger.payload",
        effects="none",
        outputs=(Port("payload"),),
        parameters={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Idempotency key; a second tick with it starts no run"},
                "inputSchema": {"type": "object", "description": "JSON Schema the payload must match"},
            },
        },
        ui=_form(
            ("key", _f("Start name", "text", "A second start with the same name runs nothing")),
            (
                "inputSchema",
                _f(
                    "Input form",
                    "json",
                    "A scheduled run's input is the time it was due (dueAt). The schema may not require anything else.",
                ),
            ),
        ),
        start=StartSpec(
            kind="schedule",
            title="Fire now",
            action="Start scheduled run",
            via="schedule",
            form_parameter="inputSchema",
        ),
        schedulable=True,
    ),
    NodeType(
        id="ops.data.combine",
        version=1,
        group="data",
        label="Combine facts",
        summary="Merges the same facts from several sources, trusting the sources in the order you set.",
        how=(
            "Each field takes its value from the first source that has it, and the step records where each value came "
            "from. Where sources disagree, it lists the differences instead of choosing quietly, and can send the run "
            "down a Disagree path for a closer look. No AI is involved."
        ),
        description=(
            "Merges the same fields from several sources by a precedence per field, keeps which source each value "
            "came from, and lists the fields the sources disagree on instead of picking silently. No model."
        ),
        executor="data.combine",
        effects="none",
        inputs=MAIN_IN,
        outputs=(Port("out"),),
        # A step that asks for it leaves by `disagree` when the sources disagree, so a person can settle them.
        optional_outputs=(("onDisagreement", "port", "disagree"),),
        parameters={
            "type": "object",
            "required": ["sources"],
            "properties": {
                "sources": {
                    "type": "array",
                    "minItems": 2,
                    "items": {
                        "type": "object",
                        "required": ["name", "values"],
                        "properties": {
                            "name": {"type": "string", "minLength": 1},
                            "values": {"description": "An object of fields: " + _MAPPING},
                        },
                    },
                },
                # A field's sources in order (a field not listed takes the sources' order), and its type: digits are
                # compared as numbers only in a number or money field, so case number 00123 is not 123.
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["field"],
                        "properties": {
                            "field": {"type": "string", "minLength": 1},
                            "from": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                            "type": _titled(*_FIELD_TYPES),
                        },
                    },
                },
                "onDisagreement": {
                    "oneOf": [
                        {"const": "continue", "title": "Go on, listing the disagreements"},
                        {"const": "port", "title": "Leave by Disagree"},
                    ],
                    "default": "continue",
                    "description": "When the sources disagree: go on by out with the disagreements listed, or a "
                    "Disagree port of its own",
                },
            },
        },
        ui=_form(
            (
                "sources",
                _f(
                    "Sources",
                    "list",
                    "In order of trust: a field takes the first source that has it",
                    item=_form(("name", _f("Name", "text")), ("values", _f("Fields", "mapping"))),
                ),
            ),
            (
                "fields",
                _f(
                    "Fields",
                    "list",
                    "A field that should trust another source first, or is a number or money",
                    item=_form(
                        ("field", _f("Field", "text")),
                        ("from", _f("Sources in order", "json")),
                        ("type", _f("Type", "select")),
                    ),
                ),
            ),
            (
                "onDisagreement",
                _f("When the sources disagree", "select", "Go on, listing the disagreements, or leave by Disagree"),
            ),
        ),
    ),
    NodeType(
        id="ops.data.compute",
        version=1,
        group="data",
        label="Calculate",
        summary=(
            "Works out new values with formulas, such as the smaller of two amounts or a date twenty business days on."
        ),
        how=(
            "You name the values the formulas read, then write each formula; a later formula can use an earlier "
            "result. No AI is involved. A formula that cannot be worked out goes on to the Error path; otherwise the "
            "next step gets every result by name."
        ),
        description=(
            "Works out new values from the step's values with formulas, such as min(levy.amount, balance) or "
            "business_days(levy.served, 20), evaluated in the tool gateway's sandbox; no model."
        ),
        executor="data.compute",
        effects="none",
        inputs=MAIN_IN,
        outputs=(Port("out"), Port("error")),
        parameters={
            "type": "object",
            "required": ["expressions"],
            "properties": {
                "values": {"type": "object", "additionalProperties": {"description": _MAPPING}},
                # Formulas are code: the executor reads them as written, never resolved, and a path in one is refused
                # here so nobody expects it to be filled in. The values carry the run's data in by name.
                "expressions": {
                    "type": "object",
                    "minProperties": 1,
                    "maxProperties": 50,
                    "additionalProperties": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2000,
                        "not": {"pattern": r"\$\."},
                        "x-problem": "must be a formula using the value names, not a value picked from a step",
                        "description": "A formula over the values by name, e.g. min(levy.amount, balance)",
                    },
                },
            },
        },
        ui=_form(
            (
                "values",
                _f(
                    "Values",
                    "mappings",
                    "The data the formulas read, each by a name: a field of the input or of an earlier step",
                ),
            ),
            (
                "expressions",
                _f(
                    "Formulas",
                    "mappings",
                    "Each result's name and its formula over the values, such as the smaller of two amounts; later "
                    "formulas can use earlier results",
                ),
            ),
        ),
    ),
    NodeType(
        id="ops.data.set",
        version=1,
        group="data",
        label="Set fields",
        summary="Puts values under the names you choose, so later steps can use them.",
        how=(
            "Each value can be fixed text, a number, or something taken from the input or an earlier step. No AI is "
            "involved, so it is quick and gives the same result every time. The next step gets every field you set."
        ),
        description="Maps and renames values from the input and earlier nodes; no model.",
        executor="data.set",
        effects="none",
        inputs=MAIN_IN,
        outputs=(Port("out"),),
        parameters={
            "type": "object",
            "required": ["values"],
            "properties": {
                "values": {"type": "object", "additionalProperties": {"description": _MAPPING}},
            },
        },
        ui=_form(
            (
                "values",
                _f(
                    "Fields",
                    "mappings",
                    "Each field's value: text, a number, or a field of the input or of an earlier step",
                ),
            )
        ),
    ),
    NodeType(
        id="ops.data.match",
        version=1,
        group="data",
        label="Match",
        summary="Finds the records in a list that match one record, by rules on their fields.",
        how=(
            "A candidate matches when every All rule holds and, if you add any, at least one Any rule. Text is "
            "compared without regard to capitals or extra spaces, and an empty value never matches. Matches go on by "
            "the Matched path; with none, the step goes on by the None path."
        ),
        description=(
            "Finds the candidates that match a record by rules on their fields: every All rule and, when any are "
            "given, at least one Any rule. Text is compared without case or extra spaces, an empty value never "
            "matches, and Overlaps needs one value inside the other at the minimum length."
        ),
        executor="data.match",
        effects="none",
        inputs=MAIN_IN,
        outputs=(Port("matched"), Port("none")),
        parameters={
            "type": "object",
            "required": ["item", "candidates", "all"],
            "properties": {
                "item": {"description": "The record to match: " + _MAPPING},
                "candidates": {"description": "The list it is matched against: " + _MAPPING},
                "all": {"type": "array", "minItems": 1, "items": _MATCH_RULE},
                "any": {"type": "array", "items": _MATCH_RULE},
            },
        },
        ui=_form(
            ("item", _f("Record", "mapping", "The record to match")),
            ("candidates", _f("Candidates", "mapping", "A list from an earlier step")),
            ("all", _f("All of", "list", "Every rule must hold", item=_MATCH_RULE_FORM)),
            ("any", _f("Any of", "list", "At least one must hold, when any are given", item=_MATCH_RULE_FORM)),
        ),
    ),
    NodeType(
        id="ops.data.transform",
        version=1,
        group="data",
        label="Transform",
        summary="Copies one value from the workflow and gives it a new name.",
        how=(
            "You pick the value from the input or an earlier step and name where it goes. If that value is not there, "
            "the step goes on to the Error path instead. Otherwise the next step gets the value under its new name."
        ),
        description="Reads one path from the run and writes it under a name. A missing path takes the error port.",
        executor="data.transform",
        effects="none",
        inputs=MAIN_IN,
        outputs=(Port("out"), Port("error")),
        parameters={
            "type": "object",
            "required": ["expression"],
            "properties": {
                "expression": {"type": "string", "description": _MAPPING},
                "as": {"type": "string", "default": "value", "description": "The output field the value is written as"},
            },
        },
        ui=_form(
            ("expression", _f("Expression", "mapping", "A field of the input or of an earlier step")),
            ("as", _f("As", "text", "The output field name")),
        ),
    ),
    NodeType(
        id="ops.data.filter",
        version=1,
        group="data",
        label="Filter",
        summary="Keeps the items of a list that meet your conditions and sets the rest aside.",
        how=(
            "Each item is checked against the conditions you set, all of them or any one. The kept items go on by the "
            "Kept path and the others by the Dropped path. A list that cannot be read goes on to the Error path."
        ),
        description="Keeps or drops items of a list by field predicates. Not a second If.",
        executor="data.filter",
        effects="none",
        inputs=MAIN_IN,
        outputs=(Port("kept"), Port("dropped"), Port("error")),
        parameters={
            "type": "object",
            "required": ["items", "conditions"],
            "properties": {
                "items": {"description": "The list to filter: " + _MAPPING},
                "conditions": {"type": "array", "minItems": 1, "items": _CONDITION},
                "combine": _titled(*_COMBINE, default="all"),
            },
        },
        ui=_form(
            ("items", _f("List", "mapping", "A list from the input or an earlier step")),
            (
                "conditions",
                _f(
                    "Keep when",
                    "list",
                    "Compared against each item's fields",
                    item=_form(
                        ("left", _f("Field", "text")),
                        ("op", _f("Is", "select")),
                        ("right", _f("Compared with", "mapping")),
                    ),
                ),
            ),
            ("combine", _f("Combine", "select")),
        ),
    ),
    NodeType(
        id="ops.flow.if",
        version=1,
        group="flow",
        label="If",
        summary="Sends the workflow one of two ways, depending on whether your conditions hold.",
        how=(
            "The conditions are checked against any earlier step's results, all of them or any one. When they hold "
            "the workflow takes the True path, otherwise the False path."
        ),
        description="Routes by rules over any earlier node's output.",
        executor="flow.if",
        effects="none",
        inputs=MAIN_IN,
        outputs=(Port("true"), Port("false")),
        parameters={
            "type": "object",
            "required": ["conditions"],
            "properties": {
                "conditions": {"type": "array", "minItems": 1, "items": _CONDITION},
                "combine": _titled(*_COMBINE, default="all"),
            },
        },
        ui=_form(
            (
                "conditions",
                _f(
                    "Conditions",
                    "list",
                    "Compared in order; True when all (or any) hold",
                    item=_form(
                        ("left", _f("Value", "mapping")),
                        ("op", _f("Is", "select")),
                        ("right", _f("Compared with", "mapping")),
                    ),
                ),
            ),
            ("combine", _f("Combine", "select")),
        ),
    ),
    NodeType(
        id="ops.flow.repeat",
        version=1,
        group="flow",
        label="Repeat",
        summary="Runs a part of the workflow again until a condition holds, up to a limit you set.",
        how=(
            "Each time round, the step checks your Done when conditions. Until they hold, the workflow goes back by "
            "the Again path; once they hold it goes on by the Done path. When the limit is reached first it takes the "
            "Exhausted path, so a loop can never run forever."
        ),
        description="Leaves by again until a predicate holds or the cap is hit, so a loop cannot spin.",
        executor="flow.repeat",
        effects="none",
        inputs=MAIN_IN,
        outputs=(Port("again"), Port("done"), Port("exhausted")),
        parameters={
            "type": "object",
            "required": ["conditions"],
            "properties": {
                "conditions": {"type": "array", "minItems": 1, "items": _CONDITION},
                "combine": _titled(*_COMBINE, default="all"),
                "max": {"type": "integer", "minimum": 1, "default": 8, "description": "Most times again may fire"},
            },
        },
        ui=_form(
            (
                "conditions",
                _f(
                    "Done when",
                    "list",
                    "Compared in order; Done when all (or any) hold",
                    item=_form(
                        ("left", _f("Value", "mapping")),
                        ("op", _f("Is", "select")),
                        ("right", _f("Compared with", "mapping")),
                    ),
                ),
            ),
            ("combine", _f("Combine", "select")),
            ("max", _f("Cap", "number", "Most times the loop may run again")),
        ),
    ),
    NodeType(
        id="ops.flow.ask",
        version=1,
        group="flow",
        label="Ask",
        tries="No. It waits for the reply.",
        limit="Until the reply comes or the Time limit setting passes.",
        summary="Asks a person a question in the conversation and waits for their reply.",
        how=(
            "The workflow pauses until the reply arrives, then goes on by the Replied path with what they said. If no "
            "reply comes in time it goes on by the Timed out path; a time limit of zero times out at once."
        ),
        description="Pauses for a reply on a conversation key, then resumes. A zero deadline times out.",
        executor="flow.ask",
        effects="human",
        inputs=MAIN_IN,
        outputs=(Port("replied"), Port("timedOut")),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "What the person is asked"},
                "key": {"type": "string", "description": "Conversation key the reply is posted on"},
                "timeoutSeconds": {"type": "number", "minimum": 0, "description": "0 times out without pausing"},
            },
        },
        ui=_form(
            ("prompt", _f("Prompt", "textarea", "What the person is asked")),
            ("key", _f("Conversation", "text", "Names the conversation the reply is posted in")),
            ("timeoutSeconds", _f("Time limit (seconds)", "number", "0 times out without pausing")),
        ),
    ),
    NodeType(
        id="ops.flow.switch",
        version=1,
        group="flow",
        label="Switch",
        summary="Sends the workflow down the first of several named ways whose rules hold.",
        how=(
            "Each way out has its own rules over earlier steps' results, checked from top to bottom. The first way "
            "that fits wins; when none fits, the workflow takes the Otherwise path. No AI is involved."
        ),
        description=(
            "Several named ways out, each a set of rules over earlier steps' output; the first way whose rules hold "
            "wins, and otherwise takes the rest. No model and no code."
        ),
        executor="flow.switch",
        effects="none",
        inputs=MAIN_IN,
        outputs=(Port("otherwise"),),
        outputs_from="cases",
        extra_outputs=("otherwise",),
        parameters={
            "type": "object",
            "required": ["cases"],
            "properties": {
                "cases": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["name", "conditions"],
                        "properties": {
                            # A way out's port; `otherwise` is the Switch's own.
                            "name": {"type": "string", "minLength": 1, "not": {"const": "otherwise"}},
                            "label": {"type": "string"},
                            "conditions": {"type": "array", "minItems": 1, "items": _CONDITION},
                            "combine": _titled(*_COMBINE, default="all"),
                        },
                    },
                },
            },
        },
        ui=_form(
            (
                "cases",
                _f(
                    "Ways out",
                    "list",
                    "Checked top to bottom; the first whose rules hold wins, and otherwise takes the rest",
                    item=_form(
                        ("name", _f("Name", "text")),
                        ("label", _f("Label", "text")),
                        (
                            "conditions",
                            _f(
                                "Rules",
                                "list",
                                item=_form(
                                    ("left", _f("Value", "mapping")),
                                    ("op", _f("Is", "select")),
                                    ("right", _f("Compared with", "mapping")),
                                ),
                            ),
                        ),
                        ("combine", _f("Combine", "select")),
                    ),
                ),
            ),
        ),
    ),
    NodeType(
        id="ops.action.tool",
        version=1,
        group="action",
        label="Call a tool",
        summary="Reads from or writes to a connected app.",
        how=(
            "You pick what to do in the app, which team account to use, and the values to send. A change to the app "
            "can require a person's approval from an earlier review step first. If the app refuses, the workflow goes "
            "on to the Refused path; if it fails or does not answer, to the Error path or a Timeout path of its own. "
            "Otherwise the next step gets the app's answer."
        ),
        description=(
            "Calls a registry operation through the tool gateway with mapped inputs. Its effects are the operation's "
            "access class at run time; an operation the registry does not know counts as a write."
        ),
        executor="gateway.call",
        effects="write",
        # Owner's default; editable per step with timeoutSeconds.
        timeout_seconds=60.0,
        inputs=MAIN_IN,
        outputs=(Port("ok"), Port("refused"), Port("error")),
        # A system that does not answer in time leaves by a port of its own when the step asks.
        optional_outputs=(("onTimeout", "port", "timeout"),),
        parameters={
            "type": "object",
            "required": ["operation"],
            "properties": {
                "operation": {"type": "string", "minLength": 1, **_NOT_A_PATH},
                "input": {"type": "object", "additionalProperties": {"description": _MAPPING}},
                "approvalToken": {"description": "A token minted elsewhere for this call: " + _MAPPING},
                "approvedBy": {
                    "type": "string",
                    **_NOT_A_PATH,
                    "description": "The review node whose decision approves this write; its call and token are sent",
                },
                "timeoutSeconds": {"type": "number", "exclusiveMinimum": 0},
                "onTimeout": _titled(
                    *_TIMEOUT_WAYS,
                    default="error",
                    description="When the system does not answer in time: the Error way out, or a Timeout way out",
                ),
                "accounts": {
                    "type": "object",
                    "maxProperties": 20,
                    "additionalProperties": {"type": "string", "minLength": 1, "maxLength": 200},
                    "description": "The team account each app's call uses, by app id to account name; none set uses "
                    "the app's default. A test run uses the app's test account",
                },
            },
        },
        ui=_form(
            ("operation", _f("Operation", "source", "What this step does in the app", source="tools")),
            ("accounts", _f("Account", "account", "Which of the app's team accounts this step uses")),
            ("input", _f("Input", "mappings", "The operation's arguments")),
            (
                "approvedBy",
                _f(
                    "Approved by",
                    "source",
                    "The review whose Approve allows this change",
                    source="steps",
                    stepType="ops.flow.humanReview",
                ),
            ),
            ("approvalToken", _f("Outside approval", "mapping", "Only for an approval given outside this workflow")),
            _TIMEOUT,
            (
                "onTimeout",
                _f("When it does not answer", "select", "Take the Error way out, or a Timeout way out of its own"),
            ),
        ),
    ),
    NodeType(
        id="ops.action.send",
        version=1,
        group="action",
        label="Send a message",
        summary="Replies to the person who started the workflow, on the same channel they used.",
        how=(
            "By default it answers the original sender and keeps the original subject. It sends once and is not "
            "retried, so a person never gets the same message twice. If sending fails, the workflow goes on to the "
            "Error path."
        ),
        description="Replies on the channel that started the run, through the existing send_reply path. One attempt.",
        executor="action.send",
        effects="write",
        inputs=MAIN_IN,
        outputs=(Port("sent"), Port("error")),
        parameters={
            "type": "object",
            "properties": {
                "to": {"description": "Recipient; empty uses the inbound from/sender: " + _MAPPING},
                "subject": {"description": "Subject; empty uses Re: the inbound subject: " + _MAPPING},
                "body": {"description": "The message body: " + _MAPPING},
            },
        },
        ui=_form(
            ("to", _f("To", "mapping", "Empty uses the inbound sender")),
            ("subject", _f("Subject", "mapping", "Empty uses Re: the inbound subject")),
            ("body", _f("Body", "textarea", "The message body")),
        ),
    ),
    NodeType(
        id="ops.ai.agent",
        version=1,
        group="ai",
        label="Agent",
        summary="Hands the work to one of your published agents, with its own tools and knowledge.",
        how=(
            "The agent reads the prompt and the values you pass, and can use its tools within the limits you set. If "
            "you give an answer format, an answer that does not fit goes on to the Error path. Otherwise the next "
            "step gets the agent's answer."
        ),
        description=(
            "Runs a published agent's turn on the step's prompt and mapped input, with the agent's own tools and "
            "knowledge; with an output schema its answer must match it, or the step takes the error port."
        ),
        executor="kernel.turn",
        effects="model",
        inputs=MAIN_IN,
        outputs=(Port("ok"), Port("error")),
        parameters={
            "type": "object",
            "required": ["agent"],
            "properties": {
                "agent": {"type": "string", "minLength": 1, "description": "The published agent's id", **_NOT_A_PATH},
                "prompt": {"type": "string", "description": "What the agent is asked to do"},
                "input": {"type": "object", "additionalProperties": {"description": _MAPPING}},
                "outputSchema": {"type": "object", "description": "JSON Schema the answer must match"},
                "model": {
                    "type": "string",
                    "minLength": 1,
                    **_NOT_A_PATH,
                    "description": "A model alias the agent allows, for this step only; the agent's own when empty",
                },
                "maxToolCalls": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "At most this many tool calls in the step's turn, within the agent's own limit",
                },
                "timeoutSeconds": {"type": "number", "exclusiveMinimum": 0},
            },
        },
        timeout_seconds=120.0,
        ui=_form(
            ("agent", _f("Agent", "source", "A published agent", source="agents")),
            ("prompt", _f("Prompt", "textarea")),
            ("input", _f("Input", "mappings", "Values the agent reads")),
            ("outputSchema", _f("Answer format", "json", "The fields the answer must have; empty takes any answer")),
            ("model", _f("Model", "text", "A model the agent allows, for this step only; empty uses the agent's")),
            ("maxToolCalls", _f("Tool calls", "number", "At most this many in the step, within the agent's own limit")),
            _TIMEOUT,
        ),
    ),
    NodeType(
        id="ops.ai.knowledge",
        version=1,
        group="ai",
        label="Retrieve from knowledge",
        summary="Searches your team's knowledge bases for passages that answer a question.",
        how=(
            "It searches the knowledge bases you pick, the same way an agent that cites its sources does. When it "
            "finds passages it goes on by the Found path with them and where they came from; otherwise by the Not "
            "found path."
        ),
        description="Searches the team's knowledge bases the same way a citing agent does. Citations leave by found.",
        executor="ai.knowledge",
        effects="read",
        inputs=MAIN_IN,
        outputs=(Port("found"), Port("notFound")),
        parameters={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"description": "The question: " + _MAPPING},
                "kbIds": {"type": "array", "items": {"type": "string"}, "description": "Knowledge bases to search"},
                "limit": {"type": "integer", "minimum": 1, "default": 3},
            },
        },
        ui=_form(
            ("query", _f("Question", "mapping", "The question to retrieve for")),
            ("kbIds", _f("Knowledge bases", "source", "Empty searches none", source="knowledge")),
            ("limit", _f("Limit", "number", "Most passages to return")),
        ),
    ),
    NodeType(
        id="ops.ai.extract",
        version=1,
        group="ai",
        label="Extract from file",
        summary="Uses AI to read the fields you define from an uploaded file, such as an invoice or a court notice.",
        how=(
            "Each value is checked against the page and quote it came from, and gets a confidence score from those "
            "checks. When any field is below its threshold the workflow goes on by the Review path for a person to "
            "check. A file it cannot read goes on by the Unreadable path. It can also read several records from one "
            "document, scoring each the same way."
        ),
        description=(
            "Reads a file from files-service into the fields you define; each field gets a confidence from checks on "
            "its quote, page and value, never the model's own, and the run takes the review port when any field is "
            "below its threshold or the workspace floor. With Several records, it reads one record per thing the "
            "document names, each scored the same way."
        ),
        executor="ai.extract",
        effects="model",
        inputs=MAIN_IN,
        # A kind Detect cannot name, or is unsure of, takes review with no fields: a person decides what the file is,
        # and `classification` on the output says why.
        outputs=(Port("ok"), Port("review"), Port("unreadable"), Port("error")),
        # A long file is read in the background and the step waits for it holding no worker; past `waitSeconds`
        # it leaves by a port of its own when the step asks, else by error.
        optional_outputs=(("onTimeout", "port", "timeout"),),
        parameters={
            "type": "object",
            "required": ["file"],
            # The fields inline, a team's document type whose version holds them, Detect, or a full-text
            # or proposed read, which names no fields.
            "x-problem": "Say what to read: name its fields, pick a document type, or let the step detect the kind.",
            "anyOf": [
                {"required": ["fields"]},
                {"required": ["documentType"]},
                {"required": ["detect"]},
                {"required": ["read"], "properties": {"read": {"enum": ["text", "propose"]}}},
            ],
            "properties": {
                "file": {"format": "file", "description": "The files-service file id: " + _MAPPING},
                # What comes back. A path into the run takes the read a request asked for (the system extract
                # workflow carries the Files page's choice).
                "read": {
                    "oneOf": [
                        {"const": "fields", "title": "Fields"},
                        {"const": "text", "title": "Full text"},
                        {"const": "propose", "title": "Let the model propose the fields"},
                        {"type": "string", "pattern": "^\\$\\."},
                    ],
                    "description": "Fields (the default), the full text with no model call, or proposed fields",
                },
                "hint": {"type": "string", "maxLength": 200, "description": "What the document is, to propose fields"},
                "proposePages": {"anyOf": [{"type": "integer", "minimum": 1, "maximum": 20}, _A_PATH]},
                "maxPages": {"anyOf": [{"type": "integer", "minimum": 1}, _A_PATH]},
                "maxTokens": {"type": "integer", "minimum": 1},
                "detect": {
                    "type": "boolean",
                    "description": "Classify the file over the team's document types and read it with the kind found",
                },
                "documentType": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 64},
                        # A path into the run reads the version the run was started with (the system extract
                        # workflow); a path is never pinned on save.
                        "version": {
                            "anyOf": [{"type": "integer", "minimum": 1}, {"type": "string", "pattern": "^\\$\\."}]
                        },
                    },
                    "description": (
                        "A team's document type, or paths into the run naming one; saving the workflow pins a named "
                        "type's newest version when none"
                    ),
                },
                "fields": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["key", "type"],
                        "properties": {
                            "key": {
                                "type": "string",
                                "pattern": "^[a-z][a-z0-9_]{0,63}$",
                                "title": "Name",
                                "x-problem": (
                                    "must start with a lowercase letter and use only lowercase letters, digits and "
                                    "underscores"
                                ),
                            },
                            "label": {"type": "string"},
                            "type": _titled(*_FIELD_TYPES, ("enum", "One of a list")),
                            "required": {"type": "boolean"},
                            "description": {"type": "string"},
                            "options": {"type": "array", "items": {"type": "string"}},
                            "reviewBelow": {"type": "number", "minimum": 0, "maximum": 1},
                            "alwaysReview": {"type": "boolean"},
                        },
                    },
                },
                "reviewBelow": {"type": "number", "minimum": 0, "maximum": 1},
                "many": {"type": "boolean", "description": "One record per thing the document names, as `records`"},
                "ocr": {"type": "boolean"},
                "timeoutSeconds": {"type": "number", "exclusiveMinimum": 0},
                "waitSeconds": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "description": "How long a background read may take before the step gives up (default 1,200)",
                },
                "onTimeout": _titled(*_TIMEOUT_WAYS, default="error"),
            },
        },
        timeout_seconds=120.0,
        ui=_form(
            ("file", _f("File", "mapping", "The uploaded file's id")),
            ("read", _f("What to read", "select", "Fields you name, the full text, or fields the model proposes")),
            ("hint", _f("What is it?", "text", "For proposed fields: a few words, e.g. a supplier invoice")),
            ("proposePages", _f("Propose from the first pages", "number", "5 if empty")),
            ("maxPages", _f("Pages to read", "number", "Every page if empty")),
            (
                "maxTokens",
                _f(
                    "Stop after (text pieces)",
                    "number",
                    "Pieces of text of about four letters each; a long read stops early with what was read",
                ),
            ),
            (
                "detect",
                _f("Detect the kind", "switch", "Read with the document type the file is; unsure goes to review"),
            ),
            (
                "documentType",
                _f(
                    "Document type",
                    "json",
                    "The document type to read with; its version is fixed when the workflow is saved",
                ),
            ),
            (
                "fields",
                _f("Fields", "json", "The fields to read: each has a name, a label, a type and whether it is required"),
            ),
            ("reviewBelow", _f("Review below", "number", "Fields under this confidence go to a person")),
            (
                "many",
                _f("Several records", "switch", "The document names several (debtors, line items): one record each"),
            ),
            ("ocr", _f("Read scans with OCR", "switch", "Off by default; OCR'd fields score lower")),
            _TIMEOUT,
            (
                "waitSeconds",
                _f("Wait for a long read (seconds)", "number", "A long file is read in the background; 1,200 if empty"),
            ),
            (
                "onTimeout",
                _f("If the read takes longer", "select", "Take the Error way out, or a Timeout way out of its own"),
            ),
        ),
    ),
    _ai_step(
        "ops.ai.classify",
        "Classify",
        "Puts the text in one of the step's categories and leaves by that category's port; below the confidence floor, "
        "or when nothing fits, it leaves by otherwise. No saved agent, no tools.",
        {
            "categories": {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "additionalProperties": False,
                    "properties": {
                        "name": {
                            "type": "string",
                            "minLength": 1,
                            "not": {"enum": ["otherwise", "error"]},
                            "x-problem": "cannot be called Otherwise or Error; the step already has those ways out",
                        },
                        "description": {"type": "string"},
                    },
                },
            },
            "minConfidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.6},
        },
        (
            ("categories", _f("Categories", "categories", "Each category is a way out; describe what belongs in it")),
            (
                "minConfidence",
                _f("Confidence floor", "number", "Below it the step takes the Otherwise way out; 0.6 when empty"),
            ),
        ),
        required=("categories",),
        outputs=(),
        outputs_from="categories",
        extra_outputs=("otherwise", "error"),
        summary="Uses AI to sort text into one of the categories you define.",
        how=(
            "Each category is its own path out, and the workflow follows the one the text fits. When the AI is not "
            "sure enough, or nothing fits, it takes the Otherwise path. It uses no saved agent and no tools; a "
            "failure goes on to the Error path."
        ),
    ),
    _ai_step(
        "ops.ai.summarise",
        "Summarise",
        "Summarises the text, keeping names, amounts and dates as written. No saved agent, no tools.",
        {"maxWords": {"type": "integer", "minimum": 10, "maximum": 1000, "default": 120}},
        (("maxWords", _f("Words at most", "number", "120 when empty")),),
        summary="Uses AI to write a short summary of the text, keeping names, amounts and dates exactly as written.",
        how=(
            "You can set how many words the summary may use and add instructions. The next step gets the summary. It "
            "uses no saved agent and no tools; a failure goes on to the Error path."
        ),
    ),
    _ai_step(
        "ops.ai.extractText",
        "Extract from text",
        "Reads fields from text (an email body, a note): a document type's fields, or fields of its own. A field the "
        "text does not state is null, never a guess. No saved agent, no tools.",
        {
            "documentType": {
                "type": "object",
                "required": ["id"],
                "additionalProperties": False,
                "properties": {"id": {"type": "string", "minLength": 1}, "version": {"type": "integer", "minimum": 1}},
            },
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["key"],
                    "properties": {"key": {"type": "string", "minLength": 1}},
                },
            },
        },
        (
            (
                "documentType",
                _f(
                    "Document type",
                    "json",
                    "The document type whose fields to read; its newest version when none is named",
                ),
            ),
            ("fields", _f("Fields", "json", "Fields of its own, as a document type declares them")),
        ),
        summary="Uses AI to pull named fields out of text, such as an email body or a note.",
        how=(
            "It reads the fields of a document type you pick, or fields you list yourself. A field the text does not "
            "state is left empty, never guessed. The next step gets the fields; a failure goes on to the Error path."
        ),
    ),
    _ai_step(
        "ops.ai.draft",
        "Draft",
        "Writes a draft (a reply, a note) from the text and the instructions. It sends nothing: a later step or a "
        "person does. No saved agent, no tools.",
        {},
        (),
        required=("instructions",),
        summary="Uses AI to write a draft, such as a reply or a note, from the text and your instructions.",
        how=(
            "It sends nothing itself: a later step or a person does that. The next step gets the draft. It uses no "
            "saved agent and no tools; a failure goes on to the Error path."
        ),
    ),
    NodeType(
        id="ops.flow.humanReview",
        version=1,
        group="human",
        label="Human review",
        tries="No. It waits for a person instead.",
        limit=(
            "Until someone decides. The Deadline setting says when it shows as overdue, and Past the deadline says "
            "what happens then."
        ),
        summary="Pauses the workflow until a person decides, from Reviews, which way it goes.",
        how=(
            "The reviewer reads the summary, can correct values you allow, and picks one of the options, Approve and "
            "Reject by default. Each option is its own path out. Past the deadline the review shows as overdue, or, "
            "if you choose, expires and goes on by the Timeout path. Reminders can be sent while it waits."
        ),
        description="Pauses for a person in Reviews; each option is an out port. Approve and Reject are the defaults.",
        executor="review.open",
        effects="human",
        inputs=MAIN_IN,
        outputs=(Port("approve"), Port("reject")),
        outputs_from="options",
        optional_outputs=(("onTimeout", "expire", "timeout"),),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {"description": "What the reviewer reads: " + _MAPPING},
                # A value the reviewer may correct before approving (a document read's records); the step's out
                # `edited` is their correction, or the value as it was when they made none.
                "editable": {"type": "string", "description": "What the reviewer may correct: " + _MAPPING},
                "slaHours": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "description": "Hours a person has to decide; the workspace's review deadline when empty",
                },
                # People who may not decide this review whatever their role, such as whoever saved the version it
                # approves. Only ever adds refusals; the run's starter is refused separately unless they hold
                # Approvals decide in the deciding team.
                "notDecidedBy": {"description": "Emails who may not decide it: " + _MAPPING},
                # Who asked for the decision when the run's starter is not them (an event a service reported for a
                # person): refused as the starter is, unless they hold Approvals decide in the deciding team.
                "requestedBy": {"description": "Emails who asked for it: " + _MAPPING},
                # A reminder while the review still waits: a task.reminder service event every N hours, which a
                # system workflow the team configures may act on; the review keeps waiting.
                "remindEveryHours": {"type": "number", "exclusiveMinimum": 0},
                "onTimeout": _titled(
                    ("wait", "Keep waiting, shown overdue"),
                    ("expire", "Expire and take the Timeout way out"),
                    default="wait",
                    description="Past the deadline: wait (shown overdue) or expire (take the Timeout way out)",
                ),
                "approves": {
                    "type": "string",
                    "description": "The tool node whose write Approve authorises",
                    **_NOT_A_PATH,
                },
                # The task screen: a task type by id, pinned to its newest published version when the step
                # pauses unless a version is named, and the values its params read. A path reads the type from the run,
                # so one workflow can open any type (the task API's api_task).
                "taskType": {
                    "oneOf": [
                        {
                            "type": "object",
                            "required": ["id"],
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string", "minLength": 1, **_NOT_A_PATH},
                                "version": {"type": "integer", "minimum": 1},
                            },
                        },
                        {"type": "string", "pattern": r"^\$\."},
                    ]
                },
                "params": {
                    "oneOf": [{"type": "object"}, {"type": "string", "pattern": r"^\$\."}],
                    "description": "The task type's params, each " + _MAPPING[0].lower() + _MAPPING[1:],
                },
                "options": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "oneOf": [
                            {"type": "string", "minLength": 1},
                            {
                                "type": "object",
                                "required": ["name"],
                                "properties": {
                                    "name": {"type": "string", "minLength": 1},
                                    "label": {"type": "string"},
                                    # The write this option authorises, and the inputs a reviewer may set on it.
                                    "call": {
                                        "type": "object",
                                        "required": ["node"],
                                        "properties": {"node": {"type": "string", **_NOT_A_PATH}},
                                    },
                                    "inputs": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "required": ["name"],
                                            "properties": {
                                                "name": {"type": "string"},
                                                "type": _titled(
                                                    ("string", "Text"),
                                                    ("number", "Number"),
                                                    ("integer", "Whole number"),
                                                    ("boolean", "Yes or no"),
                                                ),
                                                "required": {"type": "boolean"},
                                                "minimum": {"type": "number"},
                                                "maximum": {"type": "number"},
                                                "enum": {"type": "array"},
                                            },
                                        },
                                    },
                                },
                            },
                        ]
                    },
                },
            },
        },
        ui=_form(
            ("title", _f("Title", "text")),
            ("summary", _f("Summary", "mapping", "What the reviewer reads")),
            (
                "editable",
                _f(
                    "Editable",
                    "mapping",
                    "A value the reviewer may correct; the corrected value goes on to later steps",
                ),
            ),
            ("slaHours", _f("Deadline (hours)", "number", "Empty: the workspace's review deadline")),
            ("notDecidedBy", _f("Not decided by", "mapping", "Who may not decide it, e.g. who saved what it approves")),
            (
                "requestedBy",
                _f("Requested by", "mapping", "Who asked for it; they decide only if the workspace allows"),
            ),
            (
                "onTimeout",
                _f("Past the deadline", "select", "Wait shows it overdue; Expire takes the Timeout way out"),
            ),
            ("remindEveryHours", _f("Remind every (hours)", "number", "While it waits; empty for no reminder")),
            ("options", _f("Options", "options", "Each option is a way out; Approve and Reject when empty")),
            (
                "approves",
                _f(
                    "Approves",
                    "source",
                    "The app step whose change Approve allows",
                    source="steps",
                    stepType="ops.action.tool",
                ),
            ),
            (
                "taskType",
                _f("Task type", "json", "The task screen the reviewer sees; its newest version when none is named"),
            ),
            (
                "params",
                _f(
                    "Task values",
                    "json",
                    "The values the task screen shows, each a value or a field of an earlier step",
                ),
            ),
        ),
    ),
    NodeType(
        id="ops.files.setData",
        version=1,
        group="action",
        label="Save data on file",
        summary="Saves what an earlier Extract from file step read onto the file itself.",
        how=(
            "The file then shows its document type, how many fields still wait for a person, and what was read, and "
            "the files list can filter on it. It saves as your team, so a file your team cannot see goes on to the "
            "Error path."
        ),
        description=(
            "Records on the file what an Extract from file step read: the document type and version, template or "
            "model, how many fields wait for a person, and the extraction. The files list shows and filters it. Writes "
            "as the run's team; a file the team cannot see is an error."
        ),
        executor="files.setData",
        effects="write",
        idempotent=True,
        retry=Retry(3, (1.0, 30.0)),
        inputs=MAIN_IN,
        outputs=(Port("ok"), Port("error")),
        parameters={
            "type": "object",
            "required": ["file", "read"],
            "properties": {
                "file": {"format": "file", "description": "The files-service file id: " + _MAPPING},
                "read": {"description": "The Extract from file step's output: " + _MAPPING},
                "typeName": {"description": "The document type's name as the list shows it: " + _MAPPING},
                "checked": {"type": "boolean", "description": "A person checked the fields, so none wait"},
            },
        },
        ui=_form(
            ("file", _f("File", "mapping", "The file the read came from")),
            ("read", _f("Read", "mapping", "What the Extract from file step read")),
            ("typeName", _f("Type name", "mapping", "The document type's name as the files list shows it")),
            ("checked", _f("Checked by a person", "switch", "No fields wait once a person checked them")),
        ),
    ),
    NodeType(
        id="ops.documents.correct",
        version=1,
        group="action",
        label="Save typed values",
        description=(
            "Saves what a person typed in a Human Task over an Extract from file read on its extraction, recorded as "
            "the person who decided the task, with the read checked. Each value is put in its field's type's form, "
            "and values that did not change are skipped, so a repeat saves nothing more. The file follows the "
            "extraction. Nothing typed saves nothing."
        ),
        executor="documents.correct",
        effects="write",
        idempotent=True,
        retry=Retry(3, (1.0, 30.0)),
        inputs=MAIN_IN,
        outputs=(Port("ok"), Port("error")),
        parameters={
            "type": "object",
            "required": ["read", "edited", "by"],
            "properties": {
                "read": {"description": "The Extract from file step's output: " + _MAPPING},
                "edited": {"description": "The Human Task's corrected read, such as $.nodes.check.out.edited"},
                "by": {"description": "Who decided the task, such as $.nodes.check.out.by"},
            },
        },
        ui=_form(
            ("read", _f("Read", "mapping", "The Extract from file step's output, such as $.nodes.read.out")),
            (
                "edited",
                _f("Typed values", "mapping", "The Human Task's corrected read, such as $.nodes.check.out.edited"),
            ),
            ("by", _f("Typed by", "mapping", "Who decided the task, such as $.nodes.check.out.by")),
        ),
    ),
    NodeType(
        id="ops.documents.purge",
        version=1,
        group="action",
        label="Purge what was read from a file",
        summary="Removes everything that was read from a file after the file is deleted.",
        how=(
            "It clears the extracted values and examples kept for that file. Running it again removes nothing more, "
            "so a retry is safe. A failure goes on to the Error path."
        ),
        description=(
            "Removes the extractions and document type samples documents-service holds for a file that was deleted. "
            "Repeating it removes nothing more."
        ),
        executor="documents.purge",
        effects="write",
        idempotent=True,
        retry=Retry(3, (1.0, 30.0)),
        inputs=MAIN_IN,
        outputs=(Port("ok"), Port("error")),
        parameters={
            "type": "object",
            "required": ["file"],
            "properties": {"file": {"format": "file", "description": "The deleted file's id: " + _MAPPING}},
        },
        ui=_form(("file", _f("File", "mapping", "The file that was deleted"))),
    ),
    NodeType(
        id="ops.action.workflow",
        version=1,
        group="action",
        label="Start workflow",
        limit=(
            "Starting takes a moment. With Wait for them on, the Give up after setting says how long it waits for the "
            "started workflows."
        ),
        summary="Starts another of your team's workflows, once or once for each item in a list.",
        how=(
            "Each started workflow gets its own input, and a retry never starts the same one twice. Without waiting, "
            "this workflow goes on straight away. With Wait for them on, it pauses until every one has finished, then "
            "goes on with each one's outcome and result in list order, or by the Timeout path if you set a time to "
            "give up."
        ),
        description=(
            "Starts another workflow of the team, once or once for each item of a list, in this run's mode; each child "
            "is keyed by this run, step and item, so a retry never starts a second. In the input, `$.item` reads the "
            "item and `$.index` its position. With Wait for them on, the run pauses until every child has ended and "
            "goes on by `done` with each child's outcome and output in item order."
        ),
        executor="workflow.start",
        effects="write",
        idempotent=True,
        retry=Retry(3, (1.0, 30.0)),
        inputs=MAIN_IN,
        outputs=(Port("started"), Port("error")),
        # Waiting: `done` once every child ended, `timeout` when its hours pass first; `started` is not taken.
        optional_outputs=(("wait", True, "done"), ("timeoutHours", SET, "timeout")),
        outputs_unless=(("wait", True, "started"),),
        parameters={
            "type": "object",
            "required": ["workflow"],
            "properties": {
                "workflow": {"type": "string", "minLength": 1, "description": "The workflow's id", **_NOT_A_PATH},
                "input": {
                    "type": "object",
                    "additionalProperties": {"description": _MAPPING + ", or `$.item.<field>` and `$.index`"},
                },
                "forEach": {"description": "A path to a list; one child starts per item. Empty starts one."},
                "maxItems": {"type": "integer", "minimum": 1, "maximum": MAX_ITEMS, "default": DEFAULT_MAX_ITEMS},
                "wait": {"type": "boolean", "default": False},
                "batchSize": {"type": "integer", "minimum": 1, "maximum": MAX_ITEMS},
                "timeoutHours": {"type": "number", "exclusiveMinimum": 0},
                "timeoutSeconds": {"type": "number", "exclusiveMinimum": 0},
                "label": {
                    "type": "string",
                    "description": "Text naming what each child is about; `{$.item...}` reads its item",
                },
            },
        },
        ui=_form(
            ("workflow", _f("Workflow", "source", "The workflow this step starts", source="workflows")),
            ("forEach", _f("For each", "mapping", "A list from an earlier step; empty starts one workflow")),
            ("input", _f("Input", "mappings", "What each started workflow receives")),
            (
                "label",
                _f("Label", "text", "What each started workflow is about; the item's first text when empty"),
            ),
            ("maxItems", _f("Limit", "number", f"Most workflows one step starts; {DEFAULT_MAX_ITEMS} when empty")),
            (
                "wait",
                _f(
                    "Wait for them",
                    "switch",
                    "Pause until every started workflow has ended, then go on with their results",
                ),
            ),
            (
                "batchSize",
                _f("At a time", "number", "With Wait for them: most unfinished at once; empty for all"),
            ),
            ("timeoutHours", _f("Give up after", "number", "With Wait for them: hours before taking the timeout way")),
            _TIMEOUT,
        ),
    ),
    NodeType(
        id="ops.action.openCase",
        version=1,
        group="action",
        label="Open case",
        summary="Opens a case for a customer issue in your team, with this run as its first entry.",
        how=(
            "You set the subject, priority, customer and who it is assigned to. If the step is retried it finds the "
            "case it already opened instead of opening another. The next step gets the new case's id; a failure goes "
            "on to the Error path."
        ),
        description=(
            "Opens a case for a customer issue in this run's team, with the run as its first entry. Keyed by this run "
            "and step, so a retry finds the case instead of opening another; `caseId` is on the step's output."
        ),
        executor="case.open",
        effects="write",
        idempotent=True,
        retry=Retry(3, (1.0, 30.0)),
        inputs=MAIN_IN,
        outputs=(Port("opened"), Port("error")),
        parameters={
            "type": "object",
            "required": ["subject"],
            "properties": {
                "subject": {"type": "string", "minLength": 1, "description": _MAPPING},
                # A priority, or a path to one an earlier step worked out (an agent's triage); checked when it runs.
                "priority": {
                    "anyOf": [{"enum": list(CASE_PRIORITIES)}, {"type": "string", "pattern": "^\\$\\."}],
                    "default": "normal",
                },
                "customerId": {"type": "string", "description": _MAPPING},
                "customerName": {"type": "string", "description": _MAPPING},
                "assignee": {"type": "string", "description": _MAPPING},
                # The case type whose fields and order the case shows; its newest published version is pinned.
                "caseType": {"type": "string", "maxLength": 64},
                "fields": {
                    "type": "object",
                    "maxProperties": 50,
                    "additionalProperties": {"description": _MAPPING},
                    "description": "Values the case keeps by name, such as what was read from a document",
                },
                "timeoutSeconds": {"type": "number", "exclusiveMinimum": 0},
            },
        },
        ui=_form(
            ("subject", _f("Subject", "mapping", "What the issue is, in a line")),
            ("priority", _f("Priority", "select", "Sets the deadlines")),
            ("customerId", _f("Customer id", "mapping", "The customer's id in the bank's system")),
            ("customerName", _f("Customer name", "mapping")),
            ("assignee", _f("Assignee", "mapping", "A person's email; empty leaves it with the team")),
            ("caseType", _f("Case type", "text", "Which fields the case shows, and in what order")),
            ("fields", _f("Fields", "mappings", "Values the case keeps by name, such as what was read")),
            _TIMEOUT,
        ),
    ),
    NodeType(
        id="ops.action.addToCase",
        version=1,
        group="action",
        label="Add to case",
        summary="Adds this run to an existing case of your team and can move the case on.",
        how=(
            "It adds a note and values to the case, and can mark it waiting on the customer or resolved. Only a "
            "person closes a case. A case that belongs to another team, or does not exist, goes on to the Error path."
        ),
        description=(
            "Adds this run to an existing case of this run's team, by its id from an earlier step or the run's input, "
            "and can move it on: waiting on the customer, or resolved when the run has done the work. Closing a case "
            "is a person's. A case of another team, or none, takes the error port."
        ),
        executor="case.add",
        effects="write",
        idempotent=True,
        retry=Retry(3, (1.0, 30.0)),
        inputs=MAIN_IN,
        outputs=(Port("added"), Port("error")),
        parameters={
            "type": "object",
            "required": ["caseId"],
            "properties": {
                "caseId": {"type": "string", "minLength": 1, "description": _MAPPING},
                "note": {"type": "string", "description": _MAPPING},
                "fields": {
                    "type": "object",
                    "maxProperties": 50,
                    "additionalProperties": {"description": _MAPPING},
                    "description": "Values the case keeps by name, such as what was read from a document",
                },
                "status": _titled(
                    ("open", "Open"), ("waiting_on_customer", "Waiting on the customer"), ("resolved", "Resolved")
                ),
                "timeoutSeconds": {"type": "number", "exclusiveMinimum": 0},
            },
        },
        ui=_form(
            ("caseId", _f("Case", "mapping", "The case's id, from an earlier step or the run input")),
            ("note", _f("Note", "mapping", "Shown on the case's timeline beside the run")),
            ("fields", _f("Fields", "mappings", "Values added to the case's own; a name it has takes the new value")),
            ("status", _f("Move the case to", "select", "Empty leaves its status; only a person closes a case")),
            _TIMEOUT,
        ),
    ),
    NodeType(
        id="ops.flow.join",
        version=1,
        group="flow",
        label="Join",
        tries="No. It waits for the branches.",
        limit="No limit of its own: it goes on once every branch that will arrive has.",
        summary="Waits for parallel branches to finish, then goes on once with all of their results.",
        how=(
            "It waits for every step of the workflow that can still run, not only its own branches. The next step "
            "gets each branch's last result; a branch that an earlier choice sent elsewhere shows as empty."
        ),
        description=(
            "Waits for the branches connected to it, then goes on once with each branch's last step output under that "
            "step's id; a branch an earlier If or Switch sent elsewhere is null. It waits for every step of the run "
            "that can still run, not only its own branches."
        ),
        executor="flow.join",
        effects="none",
        inputs=MAIN_IN,
        outputs=(Port("out"),),
        deferred=True,
        parameters={
            "type": "object",
            # One value today: the Join goes on once every branch that can arrive has (no first-to-finish).
            "properties": {"waitFor": _titled(("all", "Every branch"), default="all")},
        },
        ui=_form(
            (
                "waitFor",
                _f(
                    "Waits for",
                    "select",
                    "Every branch that will arrive; a branch an If or Switch sent elsewhere has no value. It waits for "
                    "every step of the run that can still run, not only its own branches.",
                ),
            ),
        ),
    ),
    NodeType(
        id="ops.flow.wait",
        version=1,
        group="flow",
        label="Wait",
        tries="No. Waiting cannot fail and be tried again.",
        limit="As long as the time or date you set.",
        summary="Pauses the workflow for a while, or until a date taken from an earlier step.",
        how=(
            "When the time is up the workflow goes on by itself. A date already past goes on at once. A value that is "
            "not a date goes on to the Error path, naming the value. A date with no time means midnight in universal "
            "time."
        ),
        description=(
            "Pauses the run for a number of seconds, or until a date or date and time read from an earlier step, then "
            "goes on by `out`. A date already past goes on at once; a value that is not a date leaves by `error` with "
            "the value named. A date with no time is midnight UTC, a time with no offset is UTC."
        ),
        executor="flow.wait",
        effects="none",
        inputs=MAIN_IN,
        outputs=(Port("out"),),
        # Only a date read from a step can be wrong; a duration has no error way out to connect.
        optional_outputs=(("mode", "until", "error"),),
        parameters={
            "type": "object",
            "properties": {
                "mode": _titled(("duration", "A length of time"), ("until", "A date"), default="duration"),
                "seconds": {"type": "number", "exclusiveMinimum": 0},
                "until": {"description": "An ISO date or date and time: " + _MAPPING},
            },
            "if": {"properties": {"mode": {"const": "until"}}, "required": ["mode"]},
            "then": {"required": ["until"]},
            "else": {"required": ["seconds"]},
        },
        ui=_form(
            ("mode", _f("Wait", "select", "For a duration, or until a date")),
            ("seconds", _f("For (seconds)", "number", "With a duration: how long the run pauses")),
            ("until", _f("Until", "mapping", "With until: a date such as a response date from an earlier step")),
        ),
    ),
    NodeType(
        id="ops.flow.waitFor",
        version=1,
        group="flow",
        label="Wait for",
        tries="No. It waits for the other system.",
        limit="Until the other system answers or the Time limit setting passes.",
        summary="Waits for another system to finish its work, then goes on with the result.",
        how=(
            "The workflow pauses without holding anything up. It wakes when the other system sends its answer back, "
            "or when the event you named arrives, whichever comes first, and the next step gets that answer. With no "
            "answer in time, it goes on by the Timeout path."
        ),
        description=(
            "Waits for work another system finishes, holding no worker: an outside system posts its result to the "
            "step's resume URL with the step's token, or a service event `event` arrives carrying correlation key "
            "`key`, whichever comes first, and the run goes on by `ok` with that result. With no answer within the "
            "time limit it goes on by `timeout` with what it waited for. Set an answer schema to pick its fields in "
            "later steps."
        ),
        executor="flow.wait_for",
        effects="none",
        inputs=MAIN_IN,
        outputs=(Port("ok"), Port("timeout")),
        parameters={
            "type": "object",
            "properties": {
                "event": {
                    "type": "string",
                    "description": "A service event that also wakes the step, e.g. extraction.finished",
                },
                "key": {"description": "With event: the correlation key the event must carry: " + _MAPPING},
                "timeoutSeconds": {"type": "number", "exclusiveMinimum": 0, "default": 86400},
                "outputSchema": {"type": "object", "description": "JSON Schema of the answer the step goes on with"},
            },
            "required": ["timeoutSeconds"],
        },
        ui=_form(
            (
                "timeoutSeconds",
                _f("Time limit (seconds)", "number", "With no answer by then the run takes the Timeout way"),
            ),
            (
                "event",
                _f("Or an event", "text", "A service event that also wakes the step, such as extraction.finished"),
            ),
            (
                "key",
                _f(
                    "Event match",
                    "mapping",
                    "With an event: the value the event carries, such as an id an earlier step returned",
                ),
            ),
            (
                "outputSchema",
                _f(
                    "Answer format",
                    "json",
                    "The fields of the answer, so later steps can pick them; empty takes any answer",
                ),
            ),
        ),
    ),
    NodeType(
        id="ops.flow.end",
        version=1,
        group="flow",
        label="End",
        summary="Ends the workflow with an outcome you name.",
        how=(
            "You choose whether the run counts as succeeded or failed, and what its result is. Nothing runs after "
            "this step."
        ),
        description="Ends the run with a named outcome.",
        executor="flow.end",
        effects="none",
        inputs=MAIN_IN,
        parameters={
            "type": "object",
            "properties": {
                "outcome": {"type": "string", "default": "done"},
                # Whether this end is a failure: the run's status reads failed, whatever the outcome is named.
                "result": _titled(("succeeded", "Succeeded"), ("failed", "Failed"), default="succeeded"),
                "output": {"description": _MAPPING},
            },
        },
        ui=_form(
            ("outcome", _f("Outcome", "text", "The name the run ends with")),
            ("result", _f("Counts as", "select", "Failed marks the run as failed. Succeeded is the default")),
            ("output", _f("Output", "mapping", "The run's result: a value or a field of an earlier step")),
        ),
    ),
)


def default_registry() -> TypeRegistry:
    return TypeRegistry(BASIC_TYPES)


def start_form(definition: Mapping[str, JsonValue] | None, registry: TypeRegistry) -> Json | None:
    """The start form of the definition's trigger, resolved for its parameters: `StartSpec.view`, or None when the
    trigger declares no start by hand. A Service event trigger declares one only when its input schema has fields."""
    node = trigger_node(definition)
    if node is None:
        return None
    t = registry.find(str(node.get("type")), int(cast("str | int | float", node.get("typeVersion") or 1)))
    if t is None or t.start is None:
        return None
    parameters = cast(Mapping[str, JsonValue], node.get("parameters") or {})
    if t.start.when_schema:
        raw: object = parameters.get(t.start.form_parameter or "")
        props: object = cast(Mapping[str, JsonValue], raw).get("properties") if isinstance(raw, Mapping) else None
        if not isinstance(props, Mapping) or not props:
            return None
    return t.start.view(parameters)


def list_columns(definition: JsonValue, registry: TypeRegistry) -> ListColumns:
    """What the Workflows list reads of a definition, stored on each version (engine_definitions' description,
    trigger, startable and takes_files) so the list searches, filters and pages in SQL: its description; its trigger
    text (the description, which says what starts it as a v1 workflow's trigger does, else the trigger node's type
    label); whether a person starts it by hand (a start form, and not only from other workflows); and whether that
    form takes a file."""
    d = definition if isinstance(definition, dict) else {}
    description = str(d.get("description") or "")
    raw = d.get("nodes")
    nodes = [n for n in raw if isinstance(n, dict)] if isinstance(raw, list) else []
    versions = [n.get("typeVersion") for n in nodes]
    types = [
        registry.find(str(n.get("type")), int(v) if isinstance(v, int | float | str) and v else 0)
        for n, v in zip(nodes, versions, strict=True)
    ]
    label = next((t.label for t in types if t and t.group == "trigger"), "")
    form = start_form(d, registry)
    by_hand = form is not None and not only_from_workflows(d)
    return {
        "description": description,
        "trigger": description or label,
        "startable": by_hand,
        "takes_files": by_hand and bool(form and form["takesFiles"]),
        "mailbox": watched_mailbox(d),
    }
