# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# langgraph.graph ships without complete type information (no stubs; StateGraph.add_node is partially Unknown).
"""A workflow as data: nodes and edges in JSON with a version and a digest, compiled into a LangGraph graph.

A thread pins the version it started on, and every run and resume compiles that version, so a pause survives edits
published later. Compiled graphs are cached by digest: the same definition compiles once per process.

Node kinds: agent (a model task: classify), extract (one per attachment, fanned out by Send), collect, draft, grade,
condition (routes by a rule: score_gate, decision, route, option or outcome), human (interrupt for a review; with
`options`, a review decided by one of them), tool (send_reply, compliance_check, or any granted operation through the
tool port), end; for workflows built in the console, pass (a step with nothing to run) and agent_turn (one kernel
turn of a published agent, its definition copied into the node so the version is pinned by the digest); and for
intake from a notice (c-057), extract_records (typed records from the email and its attachments), match (one per
record, fanned out by Send: the customer it names, by the matching rule) and open_cases (one child case per match).
Routing rules: docs/architecture/definitions-and-versions.md.
"""

from __future__ import annotations

import base64
import hashlib
import operator
import time
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal, NotRequired, TypedDict, cast, get_type_hints

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_config
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send, interrupt
from pydantic import BaseModel, ConfigDict

from ops_agent_kernel.ports import ToolOutcome
from ops_agent_kernel.types import Resume, TurnRequest
from ops_agents.activities.catalog import AgentDefinition
from ops_agents.activities.tools import fill
from ops_ingest.parsers.pdf import parse_pdf
from ops_service_kit.ids import canonical_json, new_id

from .common import (
    CatalogTools,
    GraphDeps,
    agent_grants,
    approval_token,
    emit,
    interrupt_from_state,
    interrupt_to_state,
    kernel_turn,
    needs_step_up,
    reply_call,
)
from .sla import HumanSettings, review_loop, seconds

NodeKind = Literal[
    "agent",
    "extract",
    "collect",
    "draft",
    "grade",
    "condition",
    "human",
    "tool",
    "end",
    "pass",
    "agent_turn",
    "extract_records",
    "match",
    "open_cases",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NodeDef(_Model):
    id: str
    kind: NodeKind
    config: dict[str, Any] = {}


class EdgeDef(_Model):
    source: str
    target: str


class WorkflowDefinition(_Model):
    name: str
    version: int
    entry: str
    nodes: list[NodeDef]
    edges: list[EdgeDef]

    def digest(self) -> str:
        """Over the content, not the version number: the same nodes and edges are the same definition."""
        return hashlib.sha256(canonical_json(self.model_dump(mode="json", exclude={"version"})).encode()).hexdigest()

    def node(self, node_id: str) -> NodeDef | None:
        return next((n for n in self.nodes if n.id == node_id), None)


class WorkflowState(TypedDict):
    email: dict[str, Any]
    grade_overrides: NotRequired[list[float]]
    category: NotRequired[str]
    attachments: NotRequired[list[dict[str, str]]]
    extractions: Annotated[list[dict[str, Any]], operator.add]
    evidence: NotRequired[str]
    draft: NotRequired[str]
    attempts: NotRequired[int]
    score: NotRequired[float]
    feedback: NotRequired[str]
    compliance: NotRequired[str]
    review_id: NotRequired[str]
    decision: NotRequired[dict[str, Any]]
    sent: NotRequired[str]
    status: NotRequired[str]
    # Node visits as "<node>@v<version>": which version's graph ran each step.
    visited: Annotated[list[str], operator.add]
    # Set when the thread is routed to people (R9): why its remaining steps were skipped.
    route_reason: NotRequired[str]
    # An agent step that ended at a gated write: the call waiting for a review, then that review's decision.
    pending: NotRequired[dict[str, Any] | None]
    agent_decision: NotRequired[dict[str, Any] | None]
    # Intake from a notice (c-057): the text read, the records it names and how each fared against the bank.
    text: NotRequired[str]
    records: NotRequired[list[dict[str, Any]]]
    record_count: NotRequired[int]
    matches: Annotated[list[dict[str, Any]], operator.add]
    candidates: Annotated[list[dict[str, Any]], operator.add]
    unmatched: Annotated[list[dict[str, Any]], operator.add]
    children: NotRequired[list[dict[str, Any]]]
    # A levy case (one child per match): its record, customer and accounts, then what the decision did.
    record: NotRequired[dict[str, Any]]
    customer: NotRequired[dict[str, Any]]
    accounts: NotRequired[list[dict[str, Any]]]
    hold: NotRequired[dict[str, Any] | None]
    note: NotRequired[dict[str, Any] | None]
    # The last tool call's failure (e.g. the bank's 422 on a hold), shown on the case; cleared by a call that works.
    tool_error: NotRequired[dict[str, Any] | None]


class InvalidDefinitionError(ValueError):
    pass


# What a `route` condition may compare: the scalar state fields, and the email and decision fields by dotted path.
# Lists, the email object and state written only by the runtime are left out, so a route cannot depend on them.
ROUTE_FIELDS = (
    frozenset(WorkflowState.__annotations__)
    - {"email", "attachments", "extractions", "visited", "grade_overrides", "decision", "pending", "agent_decision"}
    - {"records", "matches", "candidates", "unmatched", "children", "record", "customer", "accounts"}
    - {"hold", "note", "tool_error", "text"}
) | {"email.sender", "email.subject", "email.body", "decision.decision"}
ROUTE_OPS = frozenset({"eq", "ne", "lt", "le", "gt", "ge", "in"})
ORDERED_OPS = frozenset({"lt", "le", "gt", "ge"})
# What the console shows for each operator, and the field types it applies to.
ROUTE_OP_LABELS: dict[str, tuple[str, tuple[str, ...]]] = {
    "eq": ("is", ("text", "number", "boolean")),
    "ne": ("is not", ("text", "number", "boolean")),
    "lt": ("is less than", ("number",)),
    "le": ("is at most", ("number",)),
    "gt": ("is more than", ("number",)),
    "ge": ("is at least", ("number",)),
    "in": ("is one of", ("text", "number")),
}


def route_field_types() -> dict[str, str]:
    """Each route field's type for an editor: number, boolean or text, from WorkflowState's annotations; the dotted
    email and decision fields are text."""
    hints: dict[str, Any] = get_type_hints(WorkflowState)
    kinds: dict[Any, str] = {int: "number", float: "number", bool: "boolean"}
    return {f: kinds.get(hints.get(f), "text") for f in sorted(ROUTE_FIELDS)}


class When(_Model):
    field: str
    op: str
    value: Any


class Route(_Model):
    when: When
    to: str


def _check_routes(n: NodeDef, known: set[str]) -> None:
    """A route condition: routes [{when: {field, op, value}, to}] tried in order, then `default`. Everything that
    could fail at run time (an unknown field, a target that is not a node, no route matching) fails here instead;
    the default is required, so some route always matches."""
    try:
        raw: list[Any] = n.config.get("routes") or []
        routes = [Route.model_validate(r) for r in raw]
    except ValueError as e:
        raise InvalidDefinitionError(f"Condition {n.id} has a malformed route: {e}") from e
    if not routes:
        raise InvalidDefinitionError(f"Condition {n.id} needs at least one route.")
    if n.config.get("default") not in known:
        raise InvalidDefinitionError(f"Condition {n.id} needs a default route to a node.")
    for r in routes:
        field, op, value = r.when.field, r.when.op, r.when.value
        if r.to not in known:
            raise InvalidDefinitionError(f"Condition {n.id} routes to a missing node {r.to}.")
        if field not in ROUTE_FIELDS:
            names = ", ".join(sorted(ROUTE_FIELDS))
            raise InvalidDefinitionError(f"Condition {n.id} compares unknown field {field}. Fields: {names}.")
        if op not in ROUTE_OPS:
            raise InvalidDefinitionError(f"Condition {n.id} uses unknown operator {op}.")
        if op in ORDERED_OPS and (isinstance(value, bool) or not isinstance(value, int | float)):
            raise InvalidDefinitionError(f"Condition {n.id}: {op} compares a number, not {value!r}.")
        if op == "in" and not isinstance(value, list):
            raise InvalidDefinitionError(f"Condition {n.id}: in takes a list of values.")


def _field(state: Mapping[str, Any], path: str) -> Any:
    head, _, rest = path.partition(".")
    value = state.get(head)
    return value.get(rest) if rest and isinstance(value, Mapping) else value  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


def route_matches(state: Mapping[str, Any], when: Mapping[str, Any]) -> bool:
    """One comparison. A field with no value yet matches nothing, so the next route or the default is taken."""
    actual, op, want = _field(state, when["field"]), when["op"], when["value"]
    if actual is None:
        return False
    if op == "eq":
        return bool(actual == want)
    if op == "ne":
        return bool(actual != want)
    if op == "in":
        return actual in want
    if not isinstance(actual, int | float):
        return False
    return {"lt": actual < want, "le": actual <= want, "gt": actual > want, "ge": actual >= want}[op]


# Built into every compiled workflow for R9, route remaining steps to people. Nothing in a plan reaches
# ROUTE_NODE: the Runtime writes the routing through it with update_state, and the thread goes on to
# MANUAL_NODE, the manual-handling human step, which waits for a person to complete the case.
ROUTE_NODE = "route_to_people"
MANUAL_NODE = "manual_handling"
BUILT_IN_NODES = frozenset({ROUTE_NODE, MANUAL_NODE})


def _email_text(e: dict[str, Any]) -> str:
    return f"From: {e['sender']}\nSubject: {e['subject']}\n\n{e['body']}"


def validate(d: WorkflowDefinition) -> None:
    ids = [n.id for n in d.nodes]
    if len(ids) != len(set(ids)):
        raise InvalidDefinitionError("Node ids must be unique.")
    if reserved := BUILT_IN_NODES.intersection(ids):
        raise InvalidDefinitionError(f"Node ids {sorted(reserved)} are reserved for routing to people.")
    known = set(ids)
    if d.entry not in known:
        raise InvalidDefinitionError(f"Entry {d.entry} is not a node.")
    for e in d.edges:
        if e.source not in known or e.target not in known:
            raise InvalidDefinitionError(f"Edge {e.source} → {e.target} names a missing node.")
    for n in d.nodes:
        if n.kind == "condition" and n.config.get("rule") == "route":
            _check_routes(n, known)
        elif n.kind == "condition" and n.config.get("rule") == "option":
            targets = [v for k, v in n.config.items() if k != "rule"]
            if not targets or any(t not in known for t in targets):
                raise InvalidDefinitionError(f"Condition {n.id} routes an option to a missing node.")
        elif n.kind == "condition":
            targets = [v for k, v in n.config.items() if k in ("pass", "fail", "approved", "rejected", "ok", "failed")]
            if any(t not in known for t in targets):
                raise InvalidDefinitionError(f"Condition {n.id} routes to a missing node.")
        if n.kind == "human" and n.config.get("options") is not None:
            options: list[Any] = list(n.config["options"])
            if not options or any(not option_name(o) for o in options):
                raise InvalidDefinitionError(
                    f"Human step {n.id} needs options as names or {{name, editable: [inputs]}} objects."
                )
        if n.kind == "human" and human_settings(n.config):
            try:
                s = HumanSettings.model_validate(human_settings(n.config))
                for dur in (s.sla, s.warn_at):
                    if dur is not None:
                        seconds(dur)
            except ValueError as e:
                raise InvalidDefinitionError(f"Human step {n.id} has invalid settings: {e}") from e


def option_name(option: Any) -> str:
    """An option in a human step's config: a name, or `{name, editable: [graph input names]}`; "" when malformed."""
    if isinstance(option, str):
        return option
    if isinstance(option, dict):
        name = cast(dict[str, Any], option).get("name")
        return str(name) if isinstance(name, str) else ""
    return ""


def option_editable(option: Any) -> list[str]:
    if isinstance(option, dict):
        raw: list[Any] = list(cast(dict[str, Any], option).get("editable") or [])
        return [str(x) for x in raw]
    return []


async def option_declarations(
    deps: GraphDeps, options: list[Any], calls: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """What a reviewer decides between, and what each option lets them set: for every option its call and, for each
    `editable` input, the declaration a form renders from and the decide route validates against, taken from the
    operation's own input schema (name as the operation spells it, type, required, bounds) with the proposed call's
    value as the default. Declared from the schema, so no field is special-cased anywhere."""
    directory = deps.tools or CatalogTools(deps.catalog)
    try:
        ops = {o.name: o for o in await directory.operations()}
    except Exception:
        ops = {}
    out: list[dict[str, Any]] = []
    for option in options:
        name = option_name(option)
        call = dict(calls.get(name) or {})
        inputs: list[dict[str, Any]] = []
        if call:
            op = ops.get(str(call.get("tool")))
            schema: dict[str, Any] = dict(op.input_schema) if op else {}
            props: dict[str, Any] = dict(schema.get("properties") or {})
            required_raw: list[Any] = list(schema.get("required") or [])
            required = {str(r) for r in required_raw}
            by_plain = {_plain(k): k for k in props}
            proposed: dict[str, Any] = dict(call.get("input") or {})
            for graph_name in option_editable(option):
                key = by_plain.get(_plain(graph_name)) or next(
                    (k for k in proposed if _plain(k) == _plain(graph_name)), graph_name
                )
                prop: dict[str, Any] = dict(props.get(key) or {})
                declared: dict[str, Any] = {
                    "name": key,
                    "type": str(prop.get("type") or "string"),
                    "required": key in required,
                    "default": proposed.get(key),
                }
                for bound in ("minimum", "maximum", "enum"):
                    if bound in prop:
                        declared[bound] = prop[bound]
                inputs.append(declared)
        out.append({"name": name, "inputs": inputs, "call": call or None})
    return out


def human_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    """A human step's SLA settings: its config minus `options`, which name the decisions a levy review offers."""
    return {k: v for k, v in cfg.items() if k != "options"}


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def record_matches(record: Mapping[str, Any], customer: Mapping[str, Any], *, min_address_chars: int) -> bool:
    """The matching rule (c-057): the name matches, and the address (one a substring of the other, at least
    `min_address_chars` long) or the whole last four of the SSN matches. A name alone is a candidate, never a case."""
    if _norm(record.get("name")) != _norm(customer.get("name")) or not _norm(record.get("name")):
        return False
    last4 = _norm(record.get("ssn_last4"))
    if last4 and last4 == _norm(customer.get("ssnLast4") or customer.get("ssn_last4")):
        return True
    ours, theirs = _norm(record.get("address")), _norm(customer.get("address"))
    short = min(len(ours), len(theirs))
    return short >= min_address_chars and (ours in theirs or theirs in ours)


def _plain(name: str) -> str:
    return name.replace("_", "").replace("-", "").casefold()


async def arguments_for(deps: GraphDeps, tool: str, values: Mapping[str, Any]) -> dict[str, Any]:
    """`values` keyed the way the graph names them (customerId, accountId, amount), renamed to the operation's own
    input names (an import of `/customers/{customer_id}` takes `customer_id`), matched without case or underscores.
    A value the schema does not name is passed through, so a fixture tool keeps working."""
    directory = deps.tools or CatalogTools(deps.catalog)
    try:
        op = next((o for o in await directory.operations() if o.name == tool), None)
    except Exception:
        op = None
    props: dict[str, Any] = dict(op.input_schema.get("properties") or {}) if op else {}
    by_plain = {_plain(k): k for k in props}
    return {by_plain.get(_plain(k), k): v for k, v in values.items()}


def _rows(output: Any) -> list[dict[str, Any]]:
    """Customers from a search result: the bank answers a list; the fixture lookup answers one row or `found: false`."""
    if isinstance(output, list):
        return [cast(dict[str, Any], r) for r in cast(list[Any], output) if isinstance(r, dict)]
    if isinstance(output, dict):
        row = cast(dict[str, Any], output)
        return [row] if row.get("found", True) and any(k != "found" for k in row) else []
    return []


def _customer_id(c: Mapping[str, Any]) -> str:
    return str(c.get("id") or c.get("customerId") or "")


def _account_ids(c: Mapping[str, Any]) -> list[str]:
    """The bank lists account ids; the fixture dataset, whose rows are strings, joins them with commas."""
    raw: Any = c.get("accountIds") or []
    ids: list[Any] = raw.split(",") if isinstance(raw, str) else list(cast(list[Any], raw))
    return [str(a).strip() for a in ids if str(a).strip()]


def _failure(outcome: ToolOutcome, tool: str) -> dict[str, Any]:
    """What a failed call tells the case: the gateway's error (code, status, side, message) or a refusal's text."""
    out = outcome.output
    err: dict[str, Any] = cast(dict[str, Any], out.get("error") or {}) if isinstance(out, dict) else {}
    return {
        "tool": tool,
        "status": err.get("status"),
        "code": err.get("code"),
        "message": str(err.get("message") or (out if isinstance(out, str) else "The call failed.")),
    }


async def attachment_text(deps: GraphDeps, attachment: Mapping[str, Any]) -> str:
    """An attachment's text from the files stub: a PDF (base64, as Graph sends `contentBytes`) through its text
    layer, anything else as the text it is."""
    if deps.files is None or not attachment.get("file_id"):
        return str(attachment.get("text") or "")
    content = await deps.files.read_file(str(attachment["file_id"]))
    name = str(attachment.get("name") or "")
    if name.lower().endswith(".pdf"):
        try:
            data = base64.b64decode(content, validate=True)
        except (ValueError, TypeError):
            data = content.encode()
        return parse_pdf(data, filename=name).plain_text()
    return content


async def levy_calls(
    deps: GraphDeps, state: Mapping[str, Any], review_id: str, attempt: int
) -> dict[str, dict[str, Any]]:
    """The call each levy option makes, with the input the reviewer may complete (the hold's amount): hold = a hold
    on the customer's first account for the notice's amount, flag = a note on the customer. The step key carries the
    attempt, so a decision after a failed call is a new approval of a new call."""
    record: Mapping[str, Any] = state.get("record") or {}
    customer: Mapping[str, Any] = state.get("customer") or {}
    accounts: list[Mapping[str, Any]] = list(state.get("accounts") or [])
    first: Mapping[str, Any] = accounts[0] if accounts else {}
    listed = _account_ids(customer)
    account_id = str(first.get("id") or first.get("accountId") or (listed[0] if listed else ""))
    amount = str(record.get("amount") or "").replace(",", "").replace("$", "").strip()
    reason = f"Garnishment {record.get('case_no') or ''}, {record.get('court') or ''}".strip(", ")
    cid = _customer_id(customer)
    hold = {"accountId": account_id, "amount": float(amount) if amount else 0.0, "reason": reason}
    note = {"customerId": cid, "text": f"Levy notice {record.get('case_no') or ''}: flagged, no hold placed."}
    return {
        "hold": {
            "tool": "place_hold",
            "input": await arguments_for(deps, "place_hold", hold),
            "step": f"{review_id}:hold:{attempt}",
        },
        "flag": {
            "tool": "add_customer_note",
            "input": await arguments_for(deps, "add_customer_note", note),
            "step": f"{review_id}:flag:{attempt}",
        },
    }


def compile_definition(
    d: WorkflowDefinition, deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any] | None
) -> CompiledStateGraph[Any, Any, Any, Any]:
    validate(d)

    def node_fn(n: NodeDef) -> Callable[..., Any]:
        nid, cfg = n.id, n.config
        # Each visit records the version whose graph ran the node, so a resumed thread shows which version finished it.
        tag = f"{nid}@v{d.version}"
        if n.kind == "agent":

            async def agent(state: WorkflowState) -> dict[str, Any]:
                atts = state["email"].get("attachments", [])
                limit = int(cfg.get("max_attachments", 20))
                category = await deps.models.classify(_email_text(state["email"]), list(cfg["labels"]))
                return {"category": category, "attachments": atts[:limit], "visited": [tag]}

            return agent
        if n.kind == "extract":

            async def extract(task: dict[str, Any]) -> dict[str, Any]:
                a = task["attachment"]
                facts = await deps.models.extract(task["category"], a["name"], a["text"])
                return {"extractions": [{"name": a["name"], **facts.model_dump(exclude_none=True)}], "visited": [tag]}

            return extract
        if n.kind == "collect":

            async def collect(state: WorkflowState) -> dict[str, Any]:
                rows = sorted(state["extractions"], key=lambda x: str(x["name"]))
                evidence = "\n".join(f"- {r['name']}: {r.get('summary', '')}" for r in rows) or "No attachments."
                return {"evidence": evidence, "visited": [tag]}

            return collect
        if n.kind == "draft":

            async def draft(state: WorkflowState) -> dict[str, Any]:
                text = await deps.models.draft(
                    _email_text(state["email"]), state.get("evidence", ""), state.get("feedback")
                )
                emit("text", nid, text)
                return {"draft": text, "attempts": state.get("attempts", 0) + 1, "visited": [tag]}

            return draft
        if n.kind == "grade":

            async def grade(state: WorkflowState) -> dict[str, Any]:
                attempts = state.get("attempts", 1)
                overrides = state.get("grade_overrides") or []
                if attempts <= len(overrides):
                    return {
                        "score": overrides[attempts - 1],
                        "feedback": "Seeded grade: be more specific.",
                        "visited": [tag],
                    }
                g = await deps.models.grade(_email_text(state["email"]), state.get("draft", ""))
                return {"score": g.score, "feedback": g.feedback, "visited": [tag]}

            return grade
        if n.kind == "human":
            settings = HumanSettings.model_validate(human_settings(cfg)) if human_settings(cfg) else None
            raw_options: list[Any] = list(cfg.get("options") or [])
            options: list[str] = [option_name(o) for o in raw_options]

            async def human(state: WorkflowState) -> dict[str, Any]:
                case = canonical_json([state["email"]["sender"], state["email"]["subject"], state["email"]["body"]])
                review_id = state.get("review_id") or f"REV-{hashlib.sha256(case.encode()).hexdigest()[:6].upper()}"
                payload: dict[str, Any] = {
                    "kind": "review",
                    "node": nid,
                    "review_id": review_id,
                    "draft": state.get("draft"),
                    "score": state.get("score"),
                }
                if options:
                    # A levy review: the reviewer picks one option; the call behind it is minted its own token at
                    # decision time, so each option's call is in the payload with its step key. A failed call (the
                    # bank's 422 on a hold) is shown here and the case waits for a new decision; nothing retries.
                    attempt = len([v for v in state.get("visited", []) if v.startswith(f"{nid}@")]) + 1
                    calls = await levy_calls(deps, state, review_id, attempt)
                    payload |= {
                        "options": await option_declarations(deps, raw_options, calls),
                        "record": state.get("record"),
                        "customer": state.get("customer"),
                        "accounts": state.get("accounts"),
                        "calls": calls,
                        "error": state.get("tool_error"),
                    }
                else:
                    payload["call"] = reply_call(state["email"], state.get("draft", ""), review_id)
                # A step with settings has an SLA: the timer poller resumes it with a timeout decision.
                decision = review_loop(payload, settings, interrupt) if settings else interrupt(payload)
                return {"decision": decision, "review_id": review_id, "visited": [tag]}

            return human
        if n.kind == "tool":

            async def tool(state: WorkflowState) -> dict[str, Any]:
                if cfg["tool"] == "send_reply":
                    call = reply_call(state["email"], state.get("draft", ""), state.get("review_id", ""))
                    ref = await deps.replies.send(
                        key=call["step"], approval_token=approval_token(state.get("decision")), **call["input"]
                    )
                    return {"sent": ref, "status": "replied", "visited": [tag]}
                if cfg["tool"] == "compliance_check":
                    flagged = [w for w in ("guarantee", "promise") if w in state.get("draft", "").lower()]
                    return {"compliance": "flagged: " + ", ".join(flagged) if flagged else "pass", "visited": [tag]}
                # Any granted operation through the tool port. With `call`, the input and step are the ones the
                # review's decision carries, so the approval token, bound to that input, matches what runs.
                decision = state.get("decision") or {}
                chosen: dict[str, Any] = cast(dict[str, Any], decision.get("call") or {}) if cfg.get("call") else {}
                arguments: dict[str, Any] = dict(chosen.get("input") or cfg.get("input") or {})
                key = str(chosen.get("step") or f"{state.get('review_id', nid)}:{nid}")
                # Without a gateway no token is minted; the local port accepts the policy marker (as agent_resume).
                token = str(decision.get("approval_token") or "approval:policy") if decision else None
                outcome = await deps.ports.tools.execute(cfg["tool"], arguments, key=key, approval_token=token)
                result = str(cfg.get("result") or cfg["tool"])
                if not outcome.ok:
                    failure = _failure(outcome, cfg["tool"])
                    emit("tool_failed", nid, failure)
                    return {"tool_error": failure, result: None, "visited": [tag]}
                emit("tool_result", nid, {"tool": cfg["tool"], "output": outcome.output})
                return {"tool_error": None, result: outcome.output, "visited": [tag]}

            return tool
        if n.kind == "extract_records":
            schema = str(cfg.get("schema") or "persons")

            async def extract_records(state: WorkflowState) -> dict[str, Any]:
                email = state["email"]
                parts = [_email_text(email)]
                for a in email.get("attachments", []):
                    parts.append(f"Attachment {a.get('name', '')}:\n{await attachment_text(deps, a)}")
                text = "\n\n".join(parts)
                records = await deps.models.extract_records(schema, text)
                emit("records", nid, records)
                return {"text": text, "records": records, "record_count": len(records), "visited": [tag]}

            return extract_records
        if n.kind == "match":
            min_chars = int(cfg.get("min_address_chars", 6))

            async def match(task: dict[str, Any]) -> dict[str, Any]:
                record: dict[str, Any] = task["record"]
                tools = deps.ports.tools
                query = await arguments_for(deps, cfg["search"], {"query": record.get("name", "")})
                found = await tools.execute(cfg["search"], query, key="", approval_token=None)
                if not found.ok:
                    # The bank could not be asked (the operation is not offered, or it failed): no match, and the
                    # case says why rather than passing the person off as unknown to the bank.
                    failure = _failure(found, cfg["search"])
                    emit("tool_failed", nid, failure)
                    # Fanned out per record, so the failure rides on the record (an additive key), not on a scalar.
                    return {"unmatched": [{**record, "error": failure["message"]}], "visited": [tag]}
                rows = _rows(found.output)
                hits = [c for c in rows if record_matches(record, c, min_address_chars=min_chars)]
                if not hits:
                    emit("unmatched", nid, {"record": record, "candidates": rows})
                    if rows:
                        return {"candidates": [{"record": record, "customers": rows}], "visited": [tag]}
                    return {"unmatched": [record], "visited": [tag]}
                out: list[dict[str, Any]] = []
                for hit in hits:
                    cid = _customer_id(hit)
                    customer = hit
                    if cfg.get("customer") and cid:
                        by_id = await arguments_for(deps, cfg["customer"], {"customerId": cid})
                        got = await tools.execute(cfg["customer"], by_id, key="", approval_token=None)
                        customer = _rows(got.output)[0] if got.ok and _rows(got.output) else hit
                    accounts: list[dict[str, Any]] = []
                    for aid in _account_ids(customer):
                        if cfg.get("account"):
                            by_acc = await arguments_for(deps, cfg["account"], {"accountId": aid})
                            acc = await tools.execute(cfg["account"], by_acc, key="", approval_token=None)
                            accounts.extend(_rows(acc.output) if acc.ok else [])
                    out.append({"record": record, "customer": customer, "accounts": accounts})
                emit("matched", nid, {"record": record, "customers": [_customer_id(h) for h in hits]})
                return {"matches": out, "visited": [tag]}

            return match
        if n.kind == "open_cases":

            async def open_cases(state: WorkflowState) -> dict[str, Any]:
                if deps.workflows is None:
                    raise InvalidDefinitionError("Child cases need the workflow runner, which this process lacks.")
                configurable: dict[str, Any] = get_config().get("configurable") or {}
                parent = str(configurable["thread_id"])
                children: list[dict[str, Any]] = []
                for m in state.get("matches", []):
                    record, customer = m["record"], m["customer"]
                    cid = _customer_id(customer)
                    subject = f"Levy {record.get('case_no') or ''}: {record.get('name')} ({cid})".replace("  ", " ")
                    outcome = await deps.workflows.run(
                        workflow=str(cfg["workflow"]),
                        arguments={},
                        key=f"levy:{parent}:{record.get('case_no') or record.get('name')}:{cid}",
                        parent_thread_id=parent,
                        parent_run_id=configurable.get("run_id"),
                        graph_input={
                            "email": {**state["email"], "subject": subject},
                            "record": record,
                            "customer": customer,
                            "accounts": m["accounts"],
                        },
                        meta={"startedBy": "workflow", "subject": subject, "customerId": cid},
                    )
                    output: dict[str, Any] = (
                        cast(dict[str, Any], outcome.output) if isinstance(outcome.output, dict) else {}
                    )
                    children.append(
                        {
                            "threadId": output.get("threadId"),
                            "customerId": cid,
                            "name": record.get("name"),
                            "caseNo": record.get("case_no"),
                            "status": output.get("status") if outcome.ok else "failed",
                            "outcome": output.get("outcome"),
                        }
                    )
                emit("children", nid, children)
                if not children:
                    # Records but no match: the parent lists the candidates and unmatched persons for a person to
                    # read, and says so instead of "cases opened".
                    return {"children": [], "status": "candidates_only", "visited": [tag]}
                return {"children": children, "visited": [tag]}

            return open_cases
        if n.kind == "pass":

            async def passed(state: WorkflowState) -> dict[str, Any]:
                return {"visited": [tag]}

            return passed
        if n.kind == "agent_turn":
            pinned = AgentDefinition.model_validate(cfg["agent"])

            async def agent_turn(state: WorkflowState) -> dict[str, Any]:
                # The case so far is the turn's input: the email, then what the previous agent step wrote.
                earlier = state.get("draft")
                text = _email_text(state["email"]) + (f"\n\nPrevious step:\n{earlier}" if earlier else "")
                req = TurnRequest(
                    turn_id=new_id("turn"),
                    run_id=new_id("run"),
                    settings=deps.catalog.settings_for(pinned, deps.model_alias),
                    tools=await agent_grants(deps, pinned),
                    transcript=[],
                    user_turn=text,
                    kb_ids=pinned.default_kb_ids,
                )
                result = await kernel_turn(nid, req, deps.ports, deps.meter, deps.model_alias)
                pending = interrupt_to_state(result.interrupt) if result.interrupt else None
                return {"draft": result.text, "pending": pending, "visited": [tag]}

            return agent_turn
        if n.kind == "end":

            async def end(state: WorkflowState) -> dict[str, Any]:
                return {"status": state.get("status") or str(cfg.get("status", "done")), "visited": [tag]}

            return end

        async def condition(state: WorkflowState) -> dict[str, Any]:
            return {"visited": [tag]}

        return condition

    def agent_approval(nid: str) -> Any:
        """The review for a gated write an agent step asked for: the same payload as the agent wrapper's approval, so
        Reviews, decide, the approval token and the gateway treat it like any other."""

        async def approval(state: WorkflowState) -> dict[str, Any]:
            p = state.get("pending") or {}
            definition = deps.catalog.tool(p["tool"])
            tpl = definition.approval if definition else None
            values = {k: str(v) for k, v in p["input"].items()}
            decision = interrupt(
                {
                    "kind": "approval",
                    "node": nid,
                    "review_id": f"REV-{p['action_id'][:6].upper()}",
                    "tool": p["tool"],
                    "action": fill(tpl.action, values) if tpl else p["needed"],
                    "input": p["input"],
                    "input_hash": p["input_hash"],
                    "step_up": await needs_step_up(deps, p["tool"]),
                    "reviewers": tpl.reviewers if tpl else None,
                    "call": {"tool": p["tool"], "input": p["input"], "step": p["key"]},
                    "server": p["server"],
                    "access": p["access"],
                    "action_id": p["action_id"],
                    "needed": p["needed"],
                }
            )
            return {"agent_decision": decision, "visited": [f"{nid}__approval@v{d.version}"]}

        return approval

    def agent_resume(nid: str, pinned: AgentDefinition) -> Any:
        async def resume(state: WorkflowState) -> dict[str, Any]:
            dec = state.get("agent_decision") or {}
            approved = dec.get("decision") == "approved"
            req = TurnRequest(
                turn_id=new_id("turn"),
                run_id=new_id("run"),
                settings=deps.catalog.settings_for(pinned, deps.model_alias),
                tools=await agent_grants(deps, pinned),
                resume=Resume(
                    interrupt=interrupt_from_state(state.get("pending") or {}),
                    decision="approved" if approved else "rejected",
                    reason=dec.get("reason"),
                    approval_token=(approval_token(dec) or "approval:policy") if approved else None,
                ),
            )
            result = await kernel_turn(f"{nid}__resume", req, deps.ports, deps.meter, deps.model_alias)
            pending = interrupt_to_state(result.interrupt) if result.interrupt else None
            return {
                "draft": result.text,
                "pending": pending,
                "agent_decision": None,
                "visited": [f"{nid}__resume@v{d.version}"],
            }

        return resume

    g = StateGraph(WorkflowState)
    for n in d.nodes:
        g.add_node(n.id, node_fn(n))
        if n.kind == "agent_turn":
            g.add_node(f"{n.id}__approval", agent_approval(n.id))
            g.add_node(f"{n.id}__resume", agent_resume(n.id, AgentDefinition.model_validate(n.config["agent"])))
    g.add_edge(START, d.entry)

    by_source: dict[str, list[str]] = {}
    for e in d.edges:
        by_source.setdefault(e.source, []).append(e.target)
    extract_ids = {n.id for n in d.nodes if n.kind == "extract"}
    match_ids = {n.id for n in d.nodes if n.kind == "match"}

    for n in d.nodes:
        targets = by_source.get(n.id, [])
        if n.kind == "condition":
            cfg = n.config
            if cfg["rule"] == "score_gate":
                threshold, max_attempts, ok, retry = (
                    float(cfg["threshold"]),
                    int(cfg["max_attempts"]),
                    cfg["pass"],
                    cfg["fail"],
                )

                def gate(
                    state: WorkflowState, ok: str = ok, retry: str = retry, t: float = threshold, m: int = max_attempts
                ) -> str:
                    return ok if state.get("score", 0) >= t or state.get("attempts", 0) >= m else retry

                g.add_conditional_edges(n.id, gate, [ok, retry])
            elif cfg["rule"] == "route":
                routes: list[tuple[dict[str, Any], str]] = [(r["when"], r["to"]) for r in cfg["routes"]]
                fallback: str = cfg["default"]

                def routed(
                    state: WorkflowState, routes: list[tuple[dict[str, Any], str]] = routes, fallback: str = fallback
                ) -> str:
                    return next((to for when, to in routes if route_matches(state, when)), fallback)

                g.add_conditional_edges(n.id, routed, sorted({fallback, *(to for _, to in routes)}))
            elif cfg["rule"] == "option":
                by_option: dict[str, str] = {k: str(v) for k, v in cfg.items() if k not in ("rule", "default")}
                fallback_option: str = str(cfg.get("default") or next(iter(by_option.values())))

                def chosen(
                    state: WorkflowState, by_option: dict[str, str] = by_option, fallback: str = fallback_option
                ) -> str:
                    decision = state.get("decision") or {}
                    return by_option.get(str(decision.get("option") or decision.get("decision")), fallback)

                g.add_conditional_edges(n.id, chosen, sorted({fallback_option, *by_option.values()}))
            elif cfg["rule"] == "outcome":
                ok_to, failed_to = str(cfg["ok"]), str(cfg["failed"])

                def came_out(state: WorkflowState, ok_to: str = ok_to, failed_to: str = failed_to) -> str:
                    return failed_to if state.get("tool_error") else ok_to

                g.add_conditional_edges(n.id, came_out, [ok_to, failed_to])
            else:
                yes, no = cfg["approved"], cfg["rejected"]

                def decided(state: WorkflowState, yes: str = yes, no: str = no) -> str:
                    return yes if (state.get("decision") or {}).get("decision") == "approved" else no

                g.add_conditional_edges(n.id, decided, [yes, no])
        elif n.kind == "agent_turn":
            # A gated write stops the step at its review; the resumed turn continues to the step's own targets.
            nxt: list[str] = targets or [END]
            approval_id = f"{n.id}__approval"

            def after_turn(state: WorkflowState, nxt: list[str] = nxt, approval_id: str = approval_id) -> list[str]:
                return [approval_id] if state.get("pending") else nxt

            for source in (n.id, f"{n.id}__resume"):
                g.add_conditional_edges(source, after_turn, [approval_id, *nxt])
            g.add_edge(approval_id, f"{n.id}__resume")
        elif fan := [t for t in targets if t in extract_ids]:
            target, after = fan[0], next((t for t in by_source.get(fan[0], [])), None)

            def spread(state: WorkflowState, target: str = target, after: str | None = after) -> Any:
                atts = state.get("attachments") or []
                if not atts and after:
                    return after
                return [Send(target, {"category": state.get("category", "other"), "attachment": a}) for a in atts]

            g.add_conditional_edges(n.id, spread, [target, *([after] if after else [])])
        elif fan := [t for t in targets if t in match_ids]:
            target, after = fan[0], next((t for t in by_source.get(fan[0], [])), None)

            def per_record(state: WorkflowState, target: str = target, after: str | None = after) -> Any:
                records = state.get("records") or []
                if not records and after:
                    return after
                return [Send(target, {"record": r}) for r in records]

            g.add_conditional_edges(n.id, per_record, [target, *([after] if after else [])])
        elif n.kind == "end" or not targets:
            g.add_edge(n.id, END)
        else:
            for t in targets:
                g.add_edge(n.id, t)

    async def route_to_people(state: WorkflowState) -> dict[str, Any]:
        return {}

    async def manual_handling(state: WorkflowState) -> dict[str, Any]:
        decision = interrupt(
            {
                "kind": "manual",
                "node": MANUAL_NODE,
                "reason": state.get("route_reason"),
                "review_id": state.get("review_id"),
            }
        )
        return {"decision": decision, "status": "handled_manually", "visited": [f"{MANUAL_NODE}@v{d.version}"]}

    g.add_node(ROUTE_NODE, route_to_people)
    g.add_node(MANUAL_NODE, manual_handling)
    g.add_edge(ROUTE_NODE, MANUAL_NODE)
    g.add_edge(MANUAL_NODE, END)
    return g.compile(checkpointer=checkpointer, name=f"{d.name}@v{d.version}")


class CompiledCache:
    """Compiled graphs by digest. A definition never changes under its digest, so the cache never invalidates."""

    def __init__(self, deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any] | None) -> None:
        self._deps = deps
        self._checkpointer = checkpointer
        self._graphs: dict[str, CompiledStateGraph[Any, Any, Any, Any]] = {}
        self.compiles = 0
        self.last_compile_ms = 0.0

    def get(self, d: WorkflowDefinition) -> CompiledStateGraph[Any, Any, Any, Any]:
        digest = d.digest()
        if digest not in self._graphs:
            started = time.perf_counter()
            self._graphs[digest] = compile_definition(d, self._deps, self._checkpointer)
            self.last_compile_ms = (time.perf_counter() - started) * 1000
            self.compiles += 1
        return self._graphs[digest]
