"""The node type registry: what each kind of node is, read by the editor, the validator and the runner alike.

A type is a definition the platform ships (.codeloop/wiki/concepts/workflow-nodes.md): a namespaced id and an
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

Effects = Literal["none", "model", "read", "write", "human"]
Group = Literal["trigger", "data", "ai", "action", "flow", "human"]
ConnectionType = Literal["main", "model", "tool", "knowledge", "memory"]

# The form a type's settings are edited in: a closed set of widgets the console renders, and a closed set of option
# sources the platform serves (GET /v1/workflows/option-sources; `steps` is the definition being edited). A pack
# ships data only, so it can neither add a widget nor run code to load options.
WIDGETS = frozenset(
    {"text", "textarea", "number", "select", "switch", "mapping", "mappings", "list", "options", "source", "json"}
)
OPTION_SOURCES = frozenset({"agents", "tools", "knowledge", "workflows", "steps", "mailboxes"})


@dataclass(frozen=True)
class Port:
    name: str
    connection: ConnectionType = "main"
    label: str | None = None

    def view(self) -> dict[str, Any]:
        return {"name": self.name, "connection": self.connection, "label": self.label or self.name.capitalize()}


@dataclass(frozen=True)
class Retry:
    """`attempts` counts the first; `backoff` is the wait before the second and the cap, in seconds."""

    attempts: int
    backoff: tuple[float, float] = (0.0, 0.0)

    def wait(self, attempt: int) -> float:
        """Seconds to wait before `attempt` (2 for the first retry): doubling from the base up to the cap."""
        base, cap = self.backoff
        return min(cap, base * 2 ** max(0, attempt - 2)) if base else 0.0

    def view(self) -> dict[str, Any]:
        return {"attempts": self.attempts, "backoffSeconds": list(self.backoff)}


# Section 4's table. Human steps are not retried: a re-run finds the same review.
RETRY_BY_EFFECTS: dict[Effects, Retry] = {
    "none": Retry(3),
    "read": Retry(3, (1.0, 30.0)),
    "model": Retry(2),
    "write": Retry(1),
    "human": Retry(1),
}


# In optional_outputs and outputs_unless: any value set (not None, empty or false), as `timeoutHours` given at all.
SET = object()


def _port_rule(param: str, value: Any, port: str) -> dict[str, Any]:
    return {"parameter": param, "value": "*" if value is SET else value, "port": port}


def _holds(parameters: Mapping[str, Any] | None, param: str, value: Any) -> bool:
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
    parameters: Mapping[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    # Outputs derived from a parameter: one port per entry of that list parameter (a review's options).
    outputs_from: str | None = None
    # (parameter, value, port): an extra out port the instance has while `parameter` is `value`, e.g. a review's
    # `timeout` port when it expires.
    optional_outputs: tuple[tuple[str, Any, str], ...] = ()
    # (parameter, value, port): a declared out port the instance drops while `parameter` is `value`, e.g. Run
    # workflow's `started` while it waits for its children (c-263). A value of SET matches any value set.
    outputs_unless: tuple[tuple[str, Any, str], ...] = ()
    # Out ports every instance has besides the ones `outputs_from` lists, such as a Switch's otherwise.
    extra_outputs: tuple[str, ...] = ()
    retry: Retry | None = None
    # Runs once, when no other step of the run can still run (a LangGraph deferred node): a Join waits for every branch
    # that will arrive and never for one routed away (c-278).
    deferred: bool = False
    # A write keyed by its step, so a retry repeats nothing (starting a child run): retried by `retry`, never reconciled
    # through the tool gateway, which does not see it.
    idempotent: bool = False
    # Per-attempt limit on the executor; a node parameter `timeoutSeconds` overrides it.
    timeout_seconds: float = 30.0
    # The generated form: {"order": [...], "fields": {name: {"label", "widget", "help"?, "placeholder"?, "source"?,
    # "item"?}}}. `item` is the same shape for the objects of a `list`. Checked against `parameters` on register.
    ui: Mapping[str, Any] = field(default_factory=lambda: {"order": [], "fields": {}})

    @property
    def key(self) -> tuple[str, int]:
        return (self.id, self.version)

    def retry_policy(self) -> Retry:
        return self.retry or RETRY_BY_EFFECTS[self.effects]

    def output_ports(self, parameters: Mapping[str, Any] | None = None) -> list[str]:
        """The instance's out ports: the declared ones, or one per entry of `outputs_from` when the instance sets it."""
        ports = [p.name for p in self.outputs]
        if self.outputs_from and parameters is not None:
            raw = parameters.get(self.outputs_from)
            if isinstance(raw, list) and raw:
                ports = [option_name(o) for o in cast(list[Any], raw)]
        extra = [port for param, value, port in self.optional_outputs if _holds(parameters, param, value)]
        dropped = {port for param, value, port in self.outputs_unless if _holds(parameters, param, value)}
        return [p for p in ports + [p for p in [*self.extra_outputs, *extra] if p not in ports] if p not in dropped]

    def view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "group": self.group,
            "label": self.label,
            "description": self.description,
            "inputs": [p.view() for p in self.inputs],
            "outputs": [p.view() for p in self.outputs],
            "outputsFrom": self.outputs_from,
            "extraOutputs": list(self.extra_outputs),
            # So an editor draws the extra port while the instance's parameter holds the value, as output_ports does.
            "optionalOutputs": [_port_rule(a, v, p) for a, v, p in self.optional_outputs],
            # A declared port the instance drops while `parameter` is `value` ("*": any value set), c-263.
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
        return str(cast(dict[str, Any], option).get("name") or "")
    return str(option)


def ui_problems(schema: Mapping[str, Any], ui: Mapping[str, Any], at: str = "") -> list[str]:
    """What is wrong with a form against the parameters it edits: a field that is no parameter, a parameter with no
    field, an unknown widget or option source, a `list` with no item form. Empty when the form is sound."""
    props = cast(Mapping[str, Any], schema.get("properties") or {})
    fields = cast(Mapping[str, Any], ui.get("fields") or {})
    order = list(cast(list[str], ui.get("order") or []))
    out: list[str] = []
    if sorted(order) != sorted(fields):
        out.append(f"{at}order {order} does not list exactly the fields {sorted(fields)}")
    out += [f"{at}{name} has no form field" for name in props if name not in fields]
    for name, spec in fields.items():
        f = cast(Mapping[str, Any], spec)
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
            items = cast(Mapping[str, Any], cast(Mapping[str, Any], props[name]).get("items") or {})
            item = f.get("item")
            if not isinstance(item, Mapping):
                out.append(f"{where}a list needs an item form")
            else:
                out += ui_problems(items, cast(Mapping[str, Any], item), f"{at}{name}[].")
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
_NOT_A_PATH: dict[str, Any] = {"not": {"pattern": r"^\$\."}}
CASE_PRIORITIES = ("low", "normal", "high", "urgent")
END_RESULTS = ("succeeded", "failed")
_MAPPING = (
    "A value, or a path into the run: `$.input.<field>` or `$.nodes.<node id>.out.<field>`; in a text, paths in "
    "braces are filled in: `Levy notice: {$.input.record.name}`"
)
_CONDITION = {
    "type": "object",
    "required": ["left", "op"],
    "properties": {
        "left": {"description": _MAPPING},
        "op": {"enum": ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "exists", "empty"]},
        "right": {"description": _MAPPING},
    },
}


def _f(label: str, widget: str, help: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"label": label, "widget": widget, **({"help": help} if help else {}), **extra}


def _form(*fields: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    return {"order": [n for n, _ in fields], "fields": dict(fields)}


_MATCH_RULE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["left", "op", "right"],
    "properties": {
        "left": {"type": "string", "minLength": 1, "description": "The record's field", **_NOT_A_PATH},
        "op": {"enum": ["equals", "overlaps"]},
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
# A service event's name (c-258): dotted lower-case words, the subject first, e.g. tool_access.requested.
EVENT_NAME = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"
# A Start workflow step's limits: how many children one step may start, and its default.
MAX_ITEMS, DEFAULT_MAX_ITEMS = 500, 50
_TIMEOUT = ("timeoutSeconds", _f("Time limit (seconds)", "number", "Per attempt; the type's default when empty"))

# What every AI step (c-298) takes: the text it reads, extra instructions and a model alias. Each step adds its own.
_AI_COMMON: dict[str, Any] = {
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
    ("text", _f("Text", "mapping", "What the model reads, e.g. $.input.body")),
    ("instructions", _f("Instructions", "textarea", "Anything the model should know or do besides the step's job")),
    ("model", _f("Model", "text", "A model alias for this step; empty uses the workspace's")),
)


def _ai_step(
    type_id: str,
    label: str,
    description: str,
    own: dict[str, Any],
    form: tuple[tuple[str, dict[str, Any]], ...],
    *,
    required: tuple[str, ...] = (),
    outputs: tuple[Port, ...] = (Port("ok"), Port("error")),
    outputs_from: str | None = None,
    extra_outputs: tuple[str, ...] = (),
) -> NodeType:
    """An AI step: one model call with no tools through EnginePorts.prompts (executor ai.prompt); ai_steps.JOBS holds
    what its answer looks like and which port it leaves by."""
    return NodeType(
        id=type_id,
        version=1,
        group="ai",
        label=label,
        description=description,
        executor="ai.prompt",
        effects="model",
        inputs=MAIN_IN,
        outputs=outputs,
        outputs_from=outputs_from,
        extra_outputs=extra_outputs,
        parameters={"type": "object", "required": ["text", *required], "properties": {**_AI_COMMON, **own}},
        timeout_seconds=60.0,
        ui=_form(_AI_FORM[0], *form, *_AI_FORM[1:], _TIMEOUT),
    )


BASIC_TYPES: tuple[NodeType, ...] = (
    NodeType(
        id="ops.trigger.request",
        version=1,
        group="trigger",
        label="Request",
        description="Starts a run from an authenticated API call or a system event; the run's input is the payload.",
        executor="trigger.payload",
        effects="none",
        outputs=(Port("payload"),),
        parameters={
            "type": "object",
            "properties": {"inputSchema": {"type": "object", "description": "JSON Schema the payload must match"}},
        },
        ui=_form(
            ("inputSchema", _f("Input schema", "json", "JSON Schema the payload must match; empty accepts any object"))
        ),
    ),
    NodeType(
        id="ops.trigger.email",
        version=1,
        group="trigger",
        label="Email received",
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
                "mailbox": {"type": "string", "minLength": 1, "description": "A mailbox the team may watch"},
                "folder": {"type": "string", "default": "inbox", "description": "inbox, or a folder name"},
                "fromContains": {"type": "string", "description": "Only mail whose sender contains this"},
                "subjectContains": {"type": "string", "description": "Only mail whose subject contains this"},
                "hasAttachment": {"type": "boolean", "description": "Only mail with at least one attachment"},
                "dailyCap": {"type": "integer", "minimum": 1, "description": "Most runs to start in a UTC day"},
            },
            "required": ["mailbox"],
        },
        ui=_form(
            ("mailbox", _f("Mailbox", "source", "A team mailbox an admin set up for workflows", source="mailboxes")),
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
    ),
    NodeType(
        id="ops.trigger.event",
        version=1,
        group="trigger",
        label="Service event",
        description=(
            "Starts a run when a service reports an event, such as a file deleted or a tool access request; the run's "
            "input is the event's payload. Only a system workflow, which the platform maintains, is started by one."
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
                    "description": "The event's name, such as file.deleted",
                },
            },
            "required": ["event"],
        },
        ui=_form(("event", _f("Event", "text", "The event's name, such as file.deleted", placeholder="file.deleted"))),
    ),
    NodeType(
        id="ops.data.combine",
        version=1,
        group="data",
        label="Combine facts",
        description=(
            "Merges the same fields from several sources by a precedence per field, keeps which source each value "
            "came from, and lists the fields the sources disagree on instead of picking silently. No model."
        ),
        executor="data.combine",
        effects="none",
        inputs=MAIN_IN,
        outputs=(Port("out"),),
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
                            "type": {"enum": ["text", "number", "money", "date"]},
                        },
                    },
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
        ),
    ),
    NodeType(
        id="ops.data.compute",
        version=1,
        group="data",
        label="Calculate",
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
                        "description": "A formula over the values by name, e.g. min(levy.amount, balance)",
                    },
                },
            },
        },
        ui=_form(
            (
                "values",
                _f("Values", "mappings", "The data the formulas read, each by a name: a path to the input or a step"),
            ),
            (
                "expressions",
                _f(
                    "Formulas",
                    "mappings",
                    "Each result's name and its formula over the values, e.g. min(levy.amount, balance); later "
                    "formulas can use earlier results. Functions: min, max, abs, round, floor, ceil, sum, len, "
                    "business_days(date, n), add_days(date, n), days_between(a, b)",
                ),
            ),
        ),
    ),
    NodeType(
        id="ops.data.set",
        version=1,
        group="data",
        label="Set fields",
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
                    "Each field's value: text, a number, or a path to the input or an earlier step",
                ),
            )
        ),
    ),
    NodeType(
        id="ops.data.match",
        version=1,
        group="data",
        label="Match",
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
        id="ops.flow.if",
        version=1,
        group="flow",
        label="If",
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
                "combine": {"enum": ["all", "any"], "default": "all"},
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
        id="ops.flow.switch",
        version=1,
        group="flow",
        label="Switch",
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
                            "combine": {"enum": ["all", "any"], "default": "all"},
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
        description=(
            "Calls a registry operation through the tool gateway with mapped inputs. Its effects are the operation's "
            "access class at run time; an operation the registry does not know counts as a write."
        ),
        executor="gateway.call",
        effects="write",
        inputs=MAIN_IN,
        outputs=(Port("ok"), Port("refused"), Port("error")),
        # A system that does not answer in time leaves by a port of its own when the step asks (c-332).
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
                "onTimeout": {
                    "enum": ["error", "port"],
                    "default": "error",
                    "description": "When the system does not answer in time: the error port, or a timeout port",
                },
            },
        },
        ui=_form(
            ("operation", _f("Operation", "source", "A registry operation the tool gateway calls", source="tools")),
            ("input", _f("Input", "mappings", "The operation's arguments")),
            (
                "approvedBy",
                _f("Approved by", "source", "A review step whose Approve authorises this write", source="steps"),
            ),
            ("approvalToken", _f("Approval token", "mapping", "Only for a token minted outside this workflow")),
            _TIMEOUT,
            ("onTimeout", _f("When it does not answer", "select", "The error port, or a Timeout port of its own")),
        ),
    ),
    NodeType(
        id="ops.ai.agent",
        version=1,
        group="ai",
        label="Agent",
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
            ("outputSchema", _f("Answer schema", "json", "JSON Schema the answer must match; empty takes any answer")),
            ("model", _f("Model", "text", "A model the agent allows, for this step only; empty uses the agent's")),
            ("maxToolCalls", _f("Tool calls", "number", "At most this many in the step, within the agent's own limit")),
            _TIMEOUT,
        ),
    ),
    NodeType(
        id="ops.ai.extract",
        version=1,
        group="ai",
        label="Extract from file",
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
        # and `classification` on the output says why (c-249).
        outputs=(Port("ok"), Port("review"), Port("unreadable"), Port("error")),
        parameters={
            "type": "object",
            "required": ["file"],
            # The fields inline, a team's document type whose version holds them (c-236), or Detect (c-249).
            "anyOf": [{"required": ["fields"]}, {"required": ["documentType"]}, {"required": ["detect"]}],
            "properties": {
                "file": {"description": "The files-service file id: " + _MAPPING},
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
                        # workflow, c-250); a path is never pinned on save.
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
                            "key": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$"},
                            "label": {"type": "string"},
                            "type": {"enum": ["text", "number", "money", "date", "enum"]},
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
            },
        },
        timeout_seconds=120.0,
        ui=_form(
            ("file", _f("File", "mapping", "The uploaded file's id")),
            (
                "detect",
                _f("Detect the kind", "switch", "Read with the document type the file is; unsure goes to review"),
            ),
            (
                "documentType",
                _f("Document type", "json", "{id, version}: the version is pinned when the workflow is saved"),
            ),
            ("fields", _f("Fields", "json", "Each field: key, label, type, required, reviewBelow, alwaysReview")),
            ("reviewBelow", _f("Review below", "number", "Fields under this confidence go to a person")),
            (
                "many",
                _f("Several records", "switch", "The document names several (debtors, line items): one record each"),
            ),
            ("ocr", _f("Read scans with OCR", "switch", "Off by default; OCR'd fields score lower")),
            _TIMEOUT,
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
                        "name": {"type": "string", "minLength": 1, "not": {"enum": ["otherwise", "error"]}},
                        "description": {"type": "string"},
                    },
                },
            },
            "minConfidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.6},
        },
        (
            ("categories", _f("Categories", "options", "Each is an out port; describe what belongs in it")),
            (
                "minConfidence",
                _f("Confidence floor", "number", "Below it the step leaves by otherwise; 0.6 when empty"),
            ),
        ),
        required=("categories",),
        outputs=(),
        outputs_from="categories",
        extra_outputs=("otherwise", "error"),
    ),
    _ai_step(
        "ops.ai.summarise",
        "Summarise",
        "Summarises the text, keeping names, amounts and dates as written. No saved agent, no tools.",
        {"maxWords": {"type": "integer", "minimum": 10, "maximum": 1000, "default": 120}},
        (("maxWords", _f("Words at most", "number", "120 when empty")),),
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
            ("documentType", _f("Document type", "json", '{"id": ...}: its fields; its newest version when none')),
            ("fields", _f("Fields", "json", "Fields of its own, as a document type declares them")),
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
    ),
    NodeType(
        id="ops.flow.humanReview",
        version=1,
        group="human",
        label="Human review",
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
                # approves. Only ever adds refusals; the run's starter is refused separately by policy.
                "notDecidedBy": {"description": "Emails who may not decide it: " + _MAPPING},
                # Who asked for the decision when the run's starter is not them (an event a service reported for a
                # person): refused as the starter is, only while the tenant's requesterMayDecide is off (c-186).
                "requestedBy": {"description": "Emails who asked for it: " + _MAPPING},
                # A reminder while the review still waits (c-277): a task.reminder service event every N hours, which a
                # system workflow the team configures may act on; the review keeps waiting.
                "remindEveryHours": {"type": "number", "exclusiveMinimum": 0},
                "onTimeout": {
                    "enum": ["wait", "expire"],
                    "default": "wait",
                    "description": "Past the deadline: wait (shown overdue) or expire (leave on the timeout port)",
                },
                "approves": {
                    "type": "string",
                    "description": "The tool node whose write Approve authorises",
                    **_NOT_A_PATH,
                },
                # The task screen (c-288): a task type by id, pinned to its newest published version when the step
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
                                                "type": {"enum": ["string", "number", "integer", "boolean"]},
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
            ("editable", _f("Editable", "mapping", "A value the reviewer may correct, read on as `edited`")),
            ("slaHours", _f("Deadline (hours)", "number", "Empty: the workspace's review deadline")),
            ("notDecidedBy", _f("Not decided by", "mapping", "Who may not decide it, e.g. who saved what it approves")),
            (
                "requestedBy",
                _f("Requested by", "mapping", "Who asked for it; they decide only if the workspace allows"),
            ),
            (
                "onTimeout",
                _f("Past the deadline", "select", "Wait shows it overdue; Expire leaves on a Timeout port"),
            ),
            ("remindEveryHours", _f("Remind every (hours)", "number", "While it waits; empty for no reminder")),
            ("options", _f("Options", "options", "Each option is an out port; Approve and Reject when empty")),
            ("approves", _f("Approves", "source", "The tool step whose write Approve authorises", source="steps")),
            (
                "taskType",
                _f("Task type", "json", '{"id": ...}: the task screen; its newest version when none is named'),
            ),
            ("params", _f("Task values", "json", "The values the task type's params read, each a value or a path")),
        ),
    ),
    NodeType(
        id="ops.files.setData",
        version=1,
        group="action",
        label="Save data on file",
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
                "file": {"description": "The files-service file id: " + _MAPPING},
                "read": {"description": "The Extract from file step's output: " + _MAPPING},
                "typeName": {"description": "The document type's name as the list shows it: " + _MAPPING},
                "checked": {"type": "boolean", "description": "A person checked the fields, so none wait"},
            },
        },
        ui=_form(
            ("file", _f("File", "mapping", "The file the read came from")),
            ("read", _f("Read", "mapping", "The Extract from file step's output, such as $.nodes.read.out")),
            ("typeName", _f("Type name", "mapping", "The document type's name as the files list shows it")),
            ("checked", _f("Checked by a person", "switch", "No fields wait once a person checked them")),
        ),
    ),
    NodeType(
        id="ops.documents.purge",
        version=1,
        group="action",
        label="Purge what was read from a file",
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
            "properties": {"file": {"description": "The deleted file's id: " + _MAPPING}},
        },
        ui=_form(("file", _f("File", "mapping", "The deleted file, such as $.input.fileId"))),
    ),
    NodeType(
        id="ops.action.workflow",
        version=1,
        group="action",
        label="Start workflow",
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
        # Waiting (c-263): `done` once every child ended, `timeout` when its hours pass first; `started` is not taken.
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
            },
        },
        ui=_form(
            ("workflow", _f("Workflow", "source", "The workflow each child runs", source="workflows")),
            ("forEach", _f("For each", "mapping", "A list from an earlier step; empty starts one child")),
            ("input", _f("Input", "mappings", "The child's input; `$.item` is the current item")),
            ("maxItems", _f("Limit", "number", f"Most children one step starts; {DEFAULT_MAX_ITEMS} when empty")),
            ("wait", _f("Wait for them", "switch", "Pause until every child has ended, then go on with their results")),
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
                # The case type whose fields and order the case shows (c-291); its newest published version is pinned.
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
        description=(
            "Adds this run to an existing case of this run's team, by its id from an earlier step or the run's input. "
            "A case of another team, or none, takes the error port."
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
                "timeoutSeconds": {"type": "number", "exclusiveMinimum": 0},
            },
        },
        ui=_form(
            ("caseId", _f("Case", "mapping", "The case's id, e.g. `$.nodes.<step>.out.caseId`")),
            ("note", _f("Note", "mapping", "Shown on the case's timeline beside the run")),
            ("fields", _f("Fields", "mappings", "Values added to the case's own; a name it has takes the new value")),
            _TIMEOUT,
        ),
    ),
    NodeType(
        id="ops.flow.join",
        version=1,
        group="flow",
        label="Join",
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
            # One value today: the Join goes on once every branch that can arrive has (c-278 Q2, no first-to-finish).
            "properties": {"waitFor": {"enum": ["all"], "default": "all"}},
        },
        ui=_form(
            (
                "waitFor",
                _f(
                    "Waits for",
                    "select",
                    "Every branch that will arrive; a branch an If or Switch sent elsewhere is null. It waits for "
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
                "mode": {"enum": ["duration", "until"], "default": "duration"},
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
        id="ops.flow.end",
        version=1,
        group="flow",
        label="End",
        description="Ends the run with a named outcome.",
        executor="flow.end",
        effects="none",
        inputs=MAIN_IN,
        parameters={
            "type": "object",
            "properties": {
                "outcome": {"type": "string", "default": "done"},
                # Whether this end is a failure: the run's status reads failed, whatever the outcome is named.
                "result": {"enum": list(END_RESULTS), "default": "succeeded"},
                "output": {"description": _MAPPING},
            },
        },
        ui=_form(
            ("outcome", _f("Outcome", "text", "The name the run ends with")),
            ("result", _f("Counts as", "select", "Failed marks the run as failed. Succeeded is the default")),
            ("output", _f("Output", "mapping", "The run's result: a value or a path to an earlier step's output")),
        ),
    ),
)


def default_registry() -> TypeRegistry:
    return TypeRegistry(BASIC_TYPES)
