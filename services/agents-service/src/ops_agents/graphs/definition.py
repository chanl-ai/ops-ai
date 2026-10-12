# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# langgraph.graph ships without complete type information (no stubs; StateGraph.add_node is partially Unknown).
"""A workflow as data: nodes and edges in JSON with a version and a digest, compiled into a LangGraph graph.

A thread pins the version it started on, and every run and resume compiles that version, so a pause survives edits
published later. Compiled graphs are cached by digest: the same definition compiles once per process.

Node kinds: agent (a model task: classify), extract (one per attachment, fanned out by Send), collect, draft, grade,
condition (routes by a rule: score_gate, decision, or route), human (interrupt for a review), tool (a local stub
tool), end; and, for workflows built in the console, pass (a step with nothing to run: the trigger, or a step not
wired to a tool yet) and agent_turn (one kernel turn of a published agent, its definition copied into the node so the
version is pinned by the digest). Routing rules: docs/architecture/definitions-and-versions.md.
"""

from __future__ import annotations

import hashlib
import operator
import time
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal, NotRequired, TypedDict, get_type_hints

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send, interrupt
from pydantic import BaseModel, ConfigDict

from ops_agent_kernel.types import Resume, TurnRequest
from ops_agents.activities.catalog import AgentDefinition
from ops_agents.activities.tools import fill
from ops_service_kit.ids import canonical_json, new_id

from .common import (
    GraphDeps,
    approval_token,
    emit,
    interrupt_from_state,
    interrupt_to_state,
    kernel_turn,
    reply_call,
)
from .sla import HumanSettings, review_loop, seconds

NodeKind = Literal[
    "agent", "extract", "collect", "draft", "grade", "condition", "human", "tool", "end", "pass", "agent_turn"
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


class InvalidDefinitionError(ValueError):
    pass


# What a `route` condition may compare: the scalar state fields, and the email and decision fields by dotted path.
# Lists, the email object and state written only by the runtime are left out, so a route cannot depend on them.
ROUTE_FIELDS = (
    frozenset(WorkflowState.__annotations__)
    - {"email", "attachments", "extractions", "visited", "grade_overrides", "decision", "pending", "agent_decision"}
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
        elif n.kind == "condition":
            targets = [v for k, v in n.config.items() if k in ("pass", "fail", "approved", "rejected")]
            if any(t not in known for t in targets):
                raise InvalidDefinitionError(f"Condition {n.id} routes to a missing node.")
        if n.kind == "human" and n.config:
            try:
                s = HumanSettings.model_validate(n.config)
                for dur in (s.sla, s.warn_at):
                    if dur is not None:
                        seconds(dur)
            except ValueError as e:
                raise InvalidDefinitionError(f"Human step {n.id} has invalid settings: {e}") from e


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
            settings = HumanSettings.model_validate(cfg) if cfg else None

            async def human(state: WorkflowState) -> dict[str, Any]:
                case = canonical_json([state["email"]["sender"], state["email"]["subject"], state["email"]["body"]])
                review_id = state.get("review_id") or f"REV-{hashlib.sha256(case.encode()).hexdigest()[:6].upper()}"
                payload = {
                    "kind": "review",
                    "node": nid,
                    "review_id": review_id,
                    "draft": state.get("draft"),
                    "score": state.get("score"),
                    "call": reply_call(state["email"], state.get("draft", ""), review_id),
                }
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
                raise InvalidDefinitionError(f"Unknown tool {cfg['tool']}.")

            return tool
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
                    tools=deps.catalog.grants_for(pinned),
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
                    "moves_money": p["access"] == "money_movement",
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
                tools=deps.catalog.grants_for(pinned),
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
