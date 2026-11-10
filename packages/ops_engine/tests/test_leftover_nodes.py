"""The leftover node types, by failure mode: a missing path, a list that is not a list, an empty retrieve,
a send with no recipient, a repeat that hits its cap, and an ask that times out at once."""

from __future__ import annotations

from typing import Any, cast

from ops_agent_kernel.types import Passage
from ops_engine.compiler import (
    NodeCall,
    action_send,
    ai_knowledge,
    data_filter,
    data_transform,
    flow_ask,
    flow_repeat,
)
from ops_engine.definition import NodeInstance
from ops_engine.node_types import default_registry
from ops_engine.ports import EnginePorts, ToolResult
from tests.test_compiler import FakeTools


def call(type_id: str, params: dict[str, Any], *, ports: EnginePorts | None = None, run_input: Any = None) -> NodeCall:
    node = NodeInstance.model_validate({"id": "n", "type": type_id, "typeVersion": 1, "parameters": params})
    return NodeCall(
        run_id="run_1",
        node=node,
        type=default_registry().get(type_id, 1),
        iteration=1,
        attempt=1,
        key="run_1:n:1:1",
        params=params,
        generation=None,
        ports=ports or EnginePorts(tools=FakeTools(), reviews=cast(Any, None)),  # type: ignore[arg-type]
        run_input=run_input or {},
        scope={"input": run_input or {}, "nodes": {}},
    )


async def test_transform_maps_a_path_and_a_missing_path_errors() -> None:
    ok = await data_transform(call("ops.data.transform", {"expression": "$.input.a", "as": "b"}, run_input={"a": 1}))
    assert ok.port == "out" and ok.out == {"b": 1}
    bad = await data_transform(call("ops.data.transform", {"expression": "$.input.missing", "as": "b"}))
    assert bad.port == "error" and bad.out["code"] == "bad_path"


async def test_filter_keeps_and_drops_and_refuses_a_non_list() -> None:
    params = {"items": [{"n": 2}, {"n": 0}], "conditions": [{"left": "n", "op": "gt", "right": 1}]}
    out = await data_filter(call("ops.data.filter", params))
    assert out.port == "kept" and out.out["keptCount"] == 1 and out.out["droppedCount"] == 1
    none = await data_filter(call("ops.data.filter", {**params, "items": [{"n": 0}]}))
    assert none.port == "dropped"
    err = await data_filter(call("ops.data.filter", {"items": "nope", "conditions": params["conditions"]}))
    assert err.port == "error" and err.out["code"] == "not_a_list"


class Know:
    def __init__(self, rows: list[Passage] | None = None, boom: bool = False) -> None:
        self.rows, self.boom = rows or [], boom

    async def search(self, query: str, kb_ids: list[str]) -> list[Passage]:
        if self.boom:
            raise RuntimeError("kb down")
        return self.rows


async def test_knowledge_found_empty_and_unavailable() -> None:
    hit = Passage("d1", "Handbook", "owners", "1", "Two owners.", "kb", None)
    found = await ai_knowledge(
        call(
            "ops.ai.knowledge",
            {"query": "owners", "kbIds": ["kb"]},
            ports=EnginePorts(tools=FakeTools(), reviews=cast(Any, None), knowledge=Know([hit])),
        )  # type: ignore[arg-type]
    )
    assert found.port == "found" and found.out["passages"][0]["title"] == "Handbook"
    empty = await ai_knowledge(
        call(
            "ops.ai.knowledge",
            {"query": "none"},
            ports=EnginePorts(tools=FakeTools(), reviews=cast(Any, None), knowledge=Know()),
        )  # type: ignore[arg-type]
    )
    assert empty.port == "notFound" and empty.out["code"] == "not_found"
    down = await ai_knowledge(
        call(
            "ops.ai.knowledge",
            {"query": "x"},
            ports=EnginePorts(tools=FakeTools(), reviews=cast(Any, None), knowledge=Know(boom=True)),
        )  # type: ignore[arg-type]
    )
    assert down.port == "notFound" and down.out["code"] == "unavailable"


class SendTools(FakeTools):
    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.calls.append(operation)
        return ToolResult(True, {"status": "sent", "reference": "m1"})


async def test_send_replies_on_the_inbound_channel_and_needs_a_recipient() -> None:
    ports = EnginePorts(tools=SendTools(), reviews=cast(Any, None))  # type: ignore[arg-type]
    sent = await action_send(
        call("ops.action.send", {"body": "Thanks"}, ports=ports, run_input={"from": "a@b.test", "subject": "Hi"})
    )
    assert sent.port == "sent" and sent.out["status"] == "sent"
    missing = await action_send(call("ops.action.send", {"body": "Thanks"}))
    assert missing.port == "error" and missing.out["code"] == "no_recipient"


async def test_repeat_done_then_exhausted() -> None:
    done = await flow_repeat(call("ops.flow.repeat", {"conditions": [{"left": 1, "op": "eq", "right": 1}], "max": 2}))
    assert done.port == "done" and done.out["count"] == 1
    cap = NodeCall(
        run_id="run_1",
        node=NodeInstance.model_validate({"id": "n", "type": "ops.flow.repeat", "typeVersion": 1}),
        type=default_registry().get("ops.flow.repeat", 1),
        iteration=2,
        attempt=1,
        key="run_1:n:2:1",
        params={"conditions": [{"left": 0, "op": "eq", "right": 1}], "max": 2},
        generation=None,
        ports=EnginePorts(tools=FakeTools(), reviews=cast(Any, None)),  # type: ignore[arg-type]
        run_input={},
        scope={},
    )
    assert (await flow_repeat(cap)).port == "exhausted"


async def test_ask_times_out_on_a_zero_deadline() -> None:
    out = await flow_ask(call("ops.flow.ask", {"prompt": "?", "timeoutSeconds": 0, "key": "c1"}))
    assert out.port == "timedOut" and out.out["reason"] == "deadline"
