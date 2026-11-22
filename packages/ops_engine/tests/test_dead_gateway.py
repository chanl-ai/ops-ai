"""A write whose gateway claimed it and died, by failure mode: an unsafe write is sent again; an idempotent one is
never sent again and holds the run; a checkable one is sent again though a read shows it ran."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from ops_engine.compiler import WriteNeedsPersonError, channel
from ops_engine.journal import MemoryJournal, StepRow
from ops_engine.ports import ToolResult, WriteClass

from .test_compiler import PAYLOAD, FakeTools, Killed, build, config

LOST = ToolResult(False, {"callId": "gwc_1", "error": None}, reason="the gateway lost the call", lost=True)


class ClassedTools(FakeTools):
    """A write tool of one class whose gateway lost its first call; a checkable one's read finds it done."""

    def __init__(self, kind: WriteClass | None) -> None:
        super().__init__(access="write", recorded=LOST)
        self.kind: WriteClass | None = kind

    async def write_class(self, operation: str) -> WriteClass:
        return "unsafe" if self.kind is None else self.kind

    async def read_back(self, operation: str, input: dict[str, Any]) -> ToolResult | None:
        return ToolResult(True, {"id": input.get("customer_id"), "seen": True})


@pytest.mark.parametrize("kind", [None, "unsafe", "idempotent", "checkable"])
async def test_a_write_after_a_dead_gateway_goes_by_its_class(kind: WriteClass | None) -> None:
    run = f"dg-{kind}"
    tools, journal, saver = ClassedTools(kind), MemoryJournal(), InMemorySaver()
    with pytest.raises(Killed):
        await build(tools, journal, saver, kill="big").ainvoke({"input": PAYLOAD}, config(run), durability="sync")
    await journal.begin(StepRow(run, "lookup", 1, 1, "running", "write", f"{run}:lookup:1:1", input={}))
    graph = build(tools, journal, saver)
    if kind in (None, "unsafe"):
        with pytest.raises(WriteNeedsPersonError):
            await graph.ainvoke(None, config(run), durability="sync")
        assert tools.calls == [], "an unsafe write was sent again after its gateway died"
        return
    await graph.ainvoke(None, config(run), durability="sync")
    lookup = (await graph.aget_state(config(run))).values[channel("lookup")]
    assert lookup["port"] == "ok", lookup
    sent = [f"{run}:lookup:1:2"] if kind == "idempotent" else []
    assert tools.calls == sent, "an idempotent write is sent once more, a checkable one settled by its read"
