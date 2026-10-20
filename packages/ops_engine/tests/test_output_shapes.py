"""Output shapes (c-353), by failure mode: a step type writes a key its declared shape does not list, or never writes
one it requires, so a mapping is offered a field that never arrives; a registered type has no shape at all; a shape
that depends on a document type or an operation ignores it. Each case runs the type's own executor on fake ports and
holds what it wrote to what `shapes` declares for the port it left by."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ops_engine import default_registry
from ops_engine.compiler import EXECUTORS, NodeCall, Outcome, channel
from ops_engine.definition import NodeInstance, parse
from ops_engine.journal import MemoryJournal
from ops_engine.ports import AgentRequest, AgentResult, EnginePorts, OpenedCase
from ops_engine.shapes import BUILDERS, Shape, is_open, mismatches, shapes, unknown_fields
from tests.test_ai_steps import Prompts
from tests.test_compiler import BASIC, FakeTools, config
from tests.test_compiler import build as build_basic
from tests.test_compute_step import FakeExpressions
from tests.test_extract_step import Files
from tests.test_file_steps import READ
from tests.test_file_steps import Ports as FilePorts
from tests.test_join import build as build_fork
from tests.test_join import forked
from tests.test_match_step import call as match_call
from tests.test_start_workflow import FakeRuns

REGISTRY = default_registry()
CUSTOMER: Shape = {
    "type": "object",
    "properties": {"id": {}, "name": {}},
    "required": ["id", "name"],
    "additionalProperties": False,
}
LEVY = [{"key": "debtor", "type": "text"}, {"key": "amount", "type": "money"}]


class Lookups:
    async def document_fields(self, type_id: str, version: int | None) -> list[dict[str, Any]]:
        return LEVY

    async def operation_output(self, operation: str) -> Shape | None:
        return CUSTOMER if operation == "get_customer" else None


class Agents:
    def __init__(self, result: AgentResult) -> None:
        self.result = result

    async def turn(self, request: AgentRequest) -> AgentResult:
        return self.result


class Cases:
    async def open(self, run_id: str, fields: dict[str, Any], key: str) -> OpenedCase:
        return OpenedCase("case_1", True)

    async def add(self, run_id: str, case_id: str, note: str | None, fields: dict[str, Any] | None = None) -> None:
        return None


def node(type_id: str, **params: Any) -> NodeInstance:
    return NodeInstance.model_validate({"id": "n", "type": type_id, "typeVersion": 1, "parameters": params})


async def run(n: NodeInstance, ports: EnginePorts, run_input: Any = None) -> Outcome:
    t = REGISTRY.get(n.type, n.type_version)
    call = NodeCall("run_1", n, t, 1, 1, "run_1:n:1:1", dict(n.parameters), None, ports, run_input or {}, {})
    return await EXECUTORS[t.executor](call)


async def declared(n: NodeInstance) -> dict[str, Shape]:
    t = REGISTRY.get(n.type, n.type_version)
    return await BUILDERS[t.executor](n, t, Lookups())


def ports(**kw: Any) -> EnginePorts:
    return EnginePorts(tools=kw.pop("tools", FakeTools()), reviews=None, **kw)  # type: ignore[arg-type]


Case = tuple[str, Callable[[], Awaitable[tuple[Outcome, dict[str, Shape]]]]]


def case(n: NodeInstance, p: EnginePorts, run_input: Any = None) -> Callable[[], Awaitable[tuple[Outcome, Any]]]:
    async def go() -> tuple[Outcome, dict[str, Shape]]:
        return await run(n, p, run_input), await declared(n)

    return go


SUMMARY = {"summary": "Paid in full"}
CASES: list[tuple[str, Callable[[], Awaitable[tuple[Outcome, Any]]]]] = [
    ("ops.trigger.request", case(node("ops.trigger.request"), ports(), {"amount": 1})),
    (
        "ops.trigger.request",
        case(node("ops.trigger.request", inputSchema=CUSTOMER), ports(), {"id": "C-1", "name": "Ana"}),
    ),
    ("ops.trigger.event", case(node("ops.trigger.event", event="file.deleted"), ports(), {"fileId": "f"})),
    ("ops.data.set", case(node("ops.data.set", values={"a": 1, "b": "x"}), ports())),
    (
        "ops.data.compute",
        case(node("ops.data.compute", expressions={"amount": "a*2"}), ports(expressions=FakeExpressions())),
    ),
    (
        "ops.data.compute",
        case(node("ops.data.compute", expressions={"amount": "a/0"}), ports(expressions=FakeExpressions((None, "no")))),
    ),
    ("ops.flow.if", case(node("ops.flow.if", conditions=[{"left": 1, "op": "eq", "right": 1}]), ports())),
    (
        "ops.flow.switch",
        case(
            node("ops.flow.switch", cases=[{"name": "big", "conditions": [{"left": 5, "op": "gt", "right": 1}]}]),
            ports(),
        ),
    ),
    (
        "ops.flow.switch",
        case(
            node("ops.flow.switch", cases=[{"name": "big", "conditions": [{"left": 0, "op": "gt", "right": 1}]}]),
            ports(),
        ),
    ),
    (
        "ops.data.combine",
        case(
            node(
                "ops.data.combine",
                sources=[{"name": "a", "values": {"x": 1}}, {"name": "b", "values": {"x": 2}}],
                fields=[{"field": "x", "from": ["a", "b"]}],
            ),
            ports(),
        ),
    ),
    ("ops.action.tool", case(node("ops.action.tool", operation="get_customer", input={"customer_id": "C-1"}), ports())),
    (
        "ops.ai.agent",
        case(node("ops.ai.agent", agent="ag_1", prompt="hi"), ports(agents=Agents(AgentResult(True, text="hi")))),
    ),
    (
        "ops.ai.agent",
        case(
            node("ops.ai.agent", agent="ag_1", prompt="hi", outputSchema=CUSTOMER),
            ports(agents=Agents(AgentResult(True, {"id": "C-1", "name": "Ana"}))),
        ),
    ),
    (
        "ops.ai.classify",
        case(
            node("ops.ai.classify", text="t", categories=[{"name": "dispute"}]),
            ports(prompts=Prompts({"category": "dispute", "confidence": 0.9, "reason": "r"})),
        ),
    ),
    ("ops.ai.summarise", case(node("ops.ai.summarise", text="t"), ports(prompts=Prompts(SUMMARY)))),
    (
        "ops.ai.extractText",
        case(node("ops.ai.extractText", text="t", fields=LEVY), ports(prompts=Prompts({"debtor": "A", "amount": 9}))),
    ),
    ("ops.ai.draft", case(node("ops.ai.draft", text="t"), ports(prompts=Prompts({"subject": None, "body": "b"})))),
    ("ops.ai.draft", case(node("ops.ai.draft", text="t"), ports(prompts=Prompts(None)))),
    (
        "ops.ai.extract",
        case(
            node("ops.ai.extract", file="fil_1", documentType={"id": "levy"}),
            ports(documents=Files({"id": "ext_1", "status": "done", "outcome": "ok", "fields": {"debtor": "A"}})),
        ),
    ),
    (
        "ops.files.setData",
        case(node("ops.files.setData", file="fil_1", read=READ, typeName="Notice"), ports(file_data=FilePorts())),
    ),
    ("ops.documents.purge", case(node("ops.documents.purge", file="fil_1"), ports(documents=FilePorts()))),
    ("ops.action.workflow", case(node("ops.action.workflow", workflow="child"), ports(runs=FakeRuns()))),
    ("ops.action.openCase", case(node("ops.action.openCase", subject="Levy"), ports(cases=Cases()))),
    ("ops.action.addToCase", case(node("ops.action.addToCase", caseId="case_1"), ports(cases=Cases()))),
    ("ops.flow.wait", case(node("ops.flow.wait", mode="until", until="2020-01-01"), ports())),
    ("ops.flow.wait", case(node("ops.flow.wait", mode="until", until="next week"), ports())),
    ("ops.flow.end", case(node("ops.flow.end", outcome="done", output={"a": 1}), ports())),
    ("ops.flow.end", case(node("ops.flow.end", outcome="failed", result="failed"), ports())),
]


async def test_every_step_writes_exactly_the_shape_declared_for_the_port_it_left_by() -> None:
    problems: dict[str, list[str]] = {}
    for type_id, go in CASES:
        outcome, by_port = await go()
        if outcome.port not in by_port:
            problems[type_id] = [f"left by {outcome.port!r}, which declares no shape"]
            continue
        if found := mismatches(by_port[outcome.port], outcome.out):
            problems[f"{type_id}:{outcome.port}"] = found
    assert problems == {}, problems


async def test_a_match_step_writes_its_declared_shape() -> None:
    from tests.test_match_step import LEVY as RULES  # noqa: PLC0415 - the match test's rules, kept with its cases

    call = match_call({"name": "Ana"}, [{"name": "Ana"}], RULES)
    outcome = await EXECUTORS["data.match"](call)
    shape = (await BUILDERS["data.match"](call.node, call.type, Lookups()))[outcome.port]
    assert mismatches(shape, outcome.out) == []


async def test_a_decided_review_writes_its_declared_shape() -> None:
    tools, journal, saver = FakeTools(), MemoryJournal(), InMemorySaver()
    g = build_basic(tools, journal, saver)
    await g.ainvoke({"input": {"customerId": "C-1", "amount": 250}}, config("s1"), durability="sync")
    await g.ainvoke(Command(resume={"decision": "approved", "by": "m"}), config("s1"), durability="sync")
    env = (await g.aget_state(config("s1"))).values[channel("review")]
    review = next(n for n in BASIC.nodes if n.id == "review")
    assert mismatches((await declared(review))[env["port"]], env["out"]) == []


async def test_a_join_declares_each_branch_it_writes() -> None:
    d = forked()
    tools, journal, saver = FakeTools(), MemoryJournal(), InMemorySaver()
    g = build_fork(d, tools, journal, saver)
    await g.ainvoke({"input": {"route": True}}, config("s2"), durability="sync")
    out = (await g.aget_state(config("s2"))).values[channel("j")]["out"]
    shape = (await shapes(parse(d), REGISTRY, Lookups()))["j"]["out"]
    assert mismatches(shape, out) == [] and set(shape["required"]) == {"b", "e"}


async def test_every_registered_type_has_a_case_and_a_shape() -> None:
    covered = {t for t, _ in CASES} | {"ops.data.match", "ops.flow.humanReview", "ops.flow.join", "ops.trigger.email"}
    assert {t.id for t in REGISTRY.all()} - covered == set()
    assert {t.executor for t in REGISTRY.all() if not t.deferred} - set(BUILDERS) == set()


async def test_shapes_read_the_document_type_and_the_operation_they_name() -> None:
    extract = await declared(node("ops.ai.extract", file="f", documentType={"id": "levy"}))
    any_port = next(iter(extract.values()))
    assert set(any_port["properties"]["fields"]["properties"]) == {"debtor", "amount"}
    tool = await declared(node("ops.action.tool", operation="get_customer", input={}))
    unknown = await declared(node("ops.action.tool", operation="nobody_knows", input={}))
    assert tool["ok"] == CUSTOMER and is_open(unknown["ok"])


def mapped(read: str, operation: str = "get_customer") -> Any:
    """A request, a tool call, and a Set step that reads `$.nodes.call.out.<read>`."""
    return parse(
        {
            "schemaVersion": 2,
            "id": "reads",
            "name": "Reads",
            "nodes": [
                {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "name": "start"},
                {
                    "id": "call",
                    "type": "ops.action.tool",
                    "typeVersion": 1,
                    "name": "call",
                    "parameters": {"operation": operation, "input": {}},
                },
                {
                    "id": "use",
                    "type": "ops.data.set",
                    "typeVersion": 1,
                    "name": "use",
                    "parameters": {"values": {"who": f"$.nodes.call.out.{read}"}},
                },
                {"id": "end", "type": "ops.flow.end", "typeVersion": 1, "name": "end"},
            ],
            "connections": [
                {"from": {"node": "start", "port": "payload"}, "to": {"node": "call", "port": "in"}},
                {"from": {"node": "call", "port": "ok"}, "to": {"node": "use", "port": "in"}},
                {"from": {"node": "call", "port": "refused"}, "to": {"node": "end", "port": "in"}},
                {"from": {"node": "call", "port": "error"}, "to": {"node": "end", "port": "in"}},
                {"from": {"node": "use", "port": "out"}, "to": {"node": "end", "port": "in"}},
            ],
        }
    )


async def test_a_mapping_to_a_field_the_step_never_outputs_is_warned_and_one_into_an_open_shape_is_not() -> None:
    warned = await unknown_fields(mapped("nmae"), REGISTRY, Lookups())
    assert [(w["node"], w["code"], w["level"]) for w in warned] == [("use", "unknown_output_field", "warning")]
    assert await unknown_fields(mapped("name"), REGISTRY, Lookups()) == []
    assert await unknown_fields(mapped("anything", operation="nobody_knows"), REGISTRY, Lookups()) == []
