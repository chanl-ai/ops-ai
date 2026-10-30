"""A write whose outcome is uncertain ends the run with a reason (c-561), by failure mode: the system timed out or
answered 5xx after the call was sent and the step took its error port as if nothing happened; the gateway lost the call
and the run went on; a write still running at the gateway was retried for minutes with no end; and a write the system
refused outright was failed as uncertain instead of taking its error port."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from ops_engine.compiler import UNCERTAIN, WriteInDoubtError, WriteUncertainError, channel
from ops_engine.journal import MemoryJournal, StepRow
from ops_engine.ports import ToolResult

from .test_compiler import PAYLOAD, FakeTools, Killed, build, config


class AnsweringTools(FakeTools):
    """A write the gateway ran and answered with the outside system's error."""

    def __init__(self, error: dict[str, Any]) -> None:
        super().__init__(access="write")
        self.error = error

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.calls.append(key)
        return ToolResult(False, {"error": self.error}, reason="the operation returned an error")


@pytest.mark.parametrize(
    "error",
    [
        {
            "code": "UPSTREAM_TIMEOUT",
            "message": "crm.test accepted the connection but did not answer",
            "side": "upstream",
        },
        {"code": "UPSTREAM_ERROR", "message": "crm.test answered 503.", "status": 503, "side": "upstream"},
        {"code": "UPSTREAM_ERROR", "message": "crm.test broke off the exchange", "side": "upstream"},
    ],
)
async def test_a_write_the_system_may_have_done_fails_the_run_with_the_reason(error: dict[str, Any]) -> None:
    tools, journal = AnsweringTools(error), MemoryJournal()
    with pytest.raises(WriteUncertainError) as e:
        await build(tools, journal, InMemorySaver()).ainvoke({"input": PAYLOAD}, config("u1"), durability="sync")
    assert UNCERTAIN in e.value.plain and tools.calls == ["u1:lookup:1:1"]
    assert [r.status for r in await journal.steps("u1", "lookup", 1)] == ["error"]


async def test_a_write_the_system_refused_takes_its_error_port() -> None:
    tools = AnsweringTools({"code": "INVALID_ARGUMENTS", "message": "refused", "status": 400, "side": "upstream"})
    g = build(tools, MemoryJournal(), InMemorySaver())
    await g.ainvoke({"input": PAYLOAD}, config("u2"), durability="sync")
    assert (await g.aget_state(config("u2"))).values[channel("failed")]["out"]["outcome"] == "tool_failed"


async def test_a_write_the_gateway_lost_fails_the_run_and_is_not_sent_again() -> None:
    lost = ToolResult(False, {"callId": "gwc_1", "error": None}, reason="the gateway lost the call", lost=True)
    tools, journal, saver = FakeTools(access="write", recorded=lost), MemoryJournal(), InMemorySaver()
    with pytest.raises(Killed):
        await build(tools, journal, saver, kill="big").ainvoke({"input": PAYLOAD}, config("u3"), durability="sync")
    await journal.begin(StepRow("u3", "lookup", 1, 1, "running", "write", "u3:lookup:1:1", input={}))
    with pytest.raises(WriteUncertainError) as e:
        await build(tools, journal, saver).ainvoke(None, config("u3"), durability="sync")
    assert UNCERTAIN in e.value.plain and tools.calls == []


async def test_a_write_recorded_as_an_outside_5xx_fails_the_run() -> None:
    failed = ToolResult(False, {"callId": "gwc_2", "error": {"code": "UPSTREAM_ERROR", "status": 502}}, reason="failed")
    tools, journal, saver = FakeTools(access="write", recorded=failed), MemoryJournal(), InMemorySaver()
    with pytest.raises(Killed):
        await build(tools, journal, saver, kill="big").ainvoke({"input": PAYLOAD}, config("u4"), durability="sync")
    await journal.begin(StepRow("u4", "lookup", 1, 1, "running", "write", "u4:lookup:1:1", input={}))
    with pytest.raises(WriteUncertainError):
        await build(tools, journal, saver).ainvoke(None, config("u4"), durability="sync")
    assert tools.calls == []


@pytest.mark.parametrize(("started_ago", "raised"), [(5, WriteInDoubtError), (61, WriteUncertainError)])
async def test_a_write_still_running_is_checked_again_until_its_deadline_then_fails_the_run(
    started_ago: int, raised: type[Exception]
) -> None:
    """The tool step's deadline is 60 s: before it the pass ends in doubt and is tried later; past it the run fails."""
    tools = FakeTools(access="write", recorded=ToolResult(False, pending=True))
    journal, saver = MemoryJournal(), InMemorySaver()
    run = f"u5-{started_ago}"
    with pytest.raises(Killed):
        await build(tools, journal, saver, kill="big").ainvoke({"input": PAYLOAD}, config(run), durability="sync")
    began = (datetime.now(UTC) - timedelta(seconds=started_ago)).isoformat()
    await journal.begin(
        StepRow(run, "lookup", 1, 1, "running", "write", f"{run}:lookup:1:1", input={}, started_at=began)
    )
    with pytest.raises(raised):
        await build(tools, journal, saver).ainvoke(None, config(run), durability="sync")
    assert tools.calls == []


class HeldTools(FakeTools):
    """The gateway is still running a call under the same key (409 write_in_progress), and says so on find too."""

    def __init__(self) -> None:
        super().__init__(access="write", recorded=ToolResult(False, pending=True))

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.calls.append(key)
        return ToolResult(False, pending=True, reason="the same write is already running")


async def test_a_write_already_running_under_its_key_waits_instead_of_taking_the_refused_port() -> None:
    tools, journal = HeldTools(), MemoryJournal()
    with pytest.raises(WriteInDoubtError):
        await build(tools, journal, InMemorySaver()).ainvoke({"input": PAYLOAD}, config("u6"), durability="sync")
    assert [r.status for r in await journal.steps("u6", "lookup", 1)] == ["running"]


class SupersededTools(FakeTools):
    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        from ops_checkpointer import LeaseSupersededError  # noqa: PLC0415

        self.calls.append(key)
        raise LeaseSupersededError("lease superseded")


async def test_a_superseded_lease_stops_the_pass_instead_of_being_reconciled() -> None:
    from ops_checkpointer import LeaseSupersededError  # noqa: PLC0415

    tools = SupersededTools(access="write")
    with pytest.raises(LeaseSupersededError):
        await build(tools, MemoryJournal(), InMemorySaver()).ainvoke(
            {"input": PAYLOAD}, config("u7"), durability="sync"
        )
    assert tools.calls == ["u7:lookup:1:1"], "no reconcile, no second send"
