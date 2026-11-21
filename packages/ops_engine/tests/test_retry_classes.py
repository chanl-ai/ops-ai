"""Retries by what an error says, by failure mode: a read the outside system never got failed at once instead of
being tried again; a read refused for bad input was retried for minutes; a write the gateway never received was dropped
(the error port) instead of sent again; a write was sent again under its own blocked key; a worker that died while
re-sending a write sent it a third time on recovery; a refusal no retry can pass was tried again; a retry came before
the wait the system asked for; and a slow step kept retrying past its total duration."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from ops_engine.compiler import channel
from ops_engine.journal import MemoryJournal
from ops_engine.ports import ToolResult, outside_call

from .test_compiler import PAYLOAD, FakeTools, Killed, build, config


class ScriptedTools(FakeTools):
    """Answers each call from a script, in order: a ToolResult, or an exception the call raises. `ran` names the keys
    the gateway actually ran, which is what find() reports for a key; a key it never got has no record."""

    def __init__(self, access: str, script: list[Any]) -> None:
        super().__init__(access=access)  # pyright: ignore[reportArgumentType]
        self.script = list(script)
        self.ran: dict[str, ToolResult] = {}

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.calls.append(key)
        answer = self.script.pop(0) if self.script else ToolResult(True, {"ref": "H-1"})
        if isinstance(answer, BaseException):
            if isinstance(answer, Killed):
                self.ran[key] = ToolResult(True, {"ref": "H-2"})  # it ran; the answer never came back
            raise answer
        self.ran[key] = answer
        return answer

    async def find(self, key: str, operation: str) -> ToolResult | None:
        return self.ran.get(key)


def unsent(code: str = "CONNECT_FAILED") -> ToolResult:
    return ToolResult(False, {"error": {"code": code, "message": "no connection was made", "side": "ours"}})


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The backoff the wrapper waits between attempts, recorded instead of slept, with jitter pinned to the whole span
    so each wait reads as its longest."""
    seen: list[float] = []

    async def record(seconds: float) -> None:
        seen.append(seconds)

    monkeypatch.setattr("ops_engine.compiler.sleep", record)
    monkeypatch.setattr("ops_engine.node_types.jitter", lambda: 1.0)
    return seen


async def test_a_read_the_system_never_got_is_tried_three_times_with_backoff(waits: list[float]) -> None:
    tools = ScriptedTools("read", [unsent(), unsent("UPSTREAM_TIMEOUT")])
    g = build(tools, MemoryJournal(), InMemorySaver())
    await g.ainvoke({"input": PAYLOAD}, config("u8"), durability="sync")
    assert len(tools.calls) == 3 and waits == [5.0, 30.0]
    assert (await g.aget_state(config("u8"))).values[channel("lookup")]["port"] == "ok"


async def test_a_read_refused_for_bad_input_fails_at_once(waits: list[float]) -> None:
    bad = ToolResult(False, {"error": {"code": "INVALID_ARGUMENTS", "status": 400, "side": "upstream"}})
    tools = ScriptedTools("read", [bad])
    g = build(tools, MemoryJournal(), InMemorySaver())
    await g.ainvoke({"input": PAYLOAD}, config("u9"), durability="sync")
    assert len(tools.calls) == 1 and waits == []
    assert (await g.aget_state(config("u9"))).values[channel("failed")]["out"]["outcome"] == "tool_failed"


async def test_a_write_the_gateway_never_received_is_sent_again_under_a_new_key(waits: list[float]) -> None:
    """The call raised with no answer; the gateway has no record under the key, so it abandons it and the write is
    sent again as attempt 2, never under the blocked key."""
    tools = ScriptedTools("write", [ConnectionError("tools-service restarting")])
    tools.ran.clear()
    g = build(tools, MemoryJournal(), InMemorySaver())
    await g.ainvoke({"input": PAYLOAD}, config("u10"), durability="sync")
    assert tools.calls == ["u10:lookup:1:1", "u10:lookup:1:2"] and waits == [5.0]
    assert (await g.aget_state(config("u10"))).values[channel("lookup")]["port"] == "ok"


async def test_a_write_the_system_never_got_is_sent_again_under_a_new_key(waits: list[float]) -> None:
    tools = ScriptedTools("write", [unsent()])
    g = build(tools, MemoryJournal(), InMemorySaver())
    await g.ainvoke({"input": PAYLOAD}, config("u11"), durability="sync")
    assert tools.calls == ["u11:lookup:1:1", "u11:lookup:1:2"]


async def test_a_write_never_received_three_times_takes_its_error_port(waits: list[float]) -> None:
    tools = ScriptedTools("write", [unsent(), unsent(), unsent()])
    g = build(tools, MemoryJournal(), InMemorySaver())
    await g.ainvoke({"input": PAYLOAD}, config("u12"), durability="sync")
    assert len(tools.calls) == 3
    assert (await g.aget_state(config("u12"))).values[channel("failed")]["out"]["outcome"] == "tool_failed"


async def test_a_worker_dying_in_attempt_2_of_a_rekeyed_write_never_sends_it_a_third_time(waits: list[float]) -> None:
    tools = ScriptedTools("write", [ConnectionError("tools-service restarting"), Killed()])
    journal, saver = MemoryJournal(), InMemorySaver()
    with pytest.raises(Killed):
        await build(tools, journal, saver).ainvoke({"input": PAYLOAD}, config("u13"), durability="sync")
    g = build(tools, journal, saver)
    await g.ainvoke(None, config("u13"), durability="sync")
    assert tools.calls == ["u13:lookup:1:1", "u13:lookup:1:2"], "attempt 2 reconciled by its own key"
    assert (await g.aget_state(config("u13"))).values[channel("lookup")]["out"] == {"ref": "H-2"}


class SlowOperationTools(FakeTools):
    """An operation the gateway may take 200 s over (a code operation with timeS 185)."""

    async def deadline(self, operation: str) -> float | None:
        return 200.0


async def test_a_slow_operations_own_deadline_outlasts_the_steps_default() -> None:
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from ops_engine.compiler import WriteInDoubtError  # noqa: PLC0415
    from ops_engine.journal import StepRow  # noqa: PLC0415

    tools = SlowOperationTools(access="write", recorded=ToolResult(False, pending=True))
    journal, saver = MemoryJournal(), InMemorySaver()
    with pytest.raises(Killed):
        await build(tools, journal, saver, kill="big").ainvoke({"input": PAYLOAD}, config("u14"), durability="sync")
    began = (datetime.now(UTC) - timedelta(seconds=100)).isoformat()
    await journal.begin(
        StepRow("u14", "lookup", 1, 1, "running", "write", "u14:lookup:1:1", input={}, started_at=began)
    )
    with pytest.raises(WriteInDoubtError):
        await build(tools, journal, saver).ainvoke(None, config("u14"), durability="sync")


class Refusal(Exception):
    """An error an outside system raised with its code in the one error model, and the wait it asked for."""

    def __init__(self, code: str, retry_after: float | None = None) -> None:
        super().__init__(code)
        self.code, self.retry_after = code, retry_after


def raised(code: str, retry_after: float | None = None) -> Refusal:
    """`Refusal` marked as an outside call's failure, as a port adapter marks what its call raises."""
    try:
        with outside_call():
            raise Refusal(code, retry_after)
    except Refusal as e:
        return e


async def test_a_refusal_no_retry_can_pass_is_not_tried_again(waits: list[float]) -> None:
    tools = ScriptedTools("read", [raised("forbidden"), raised("forbidden"), raised("forbidden")])
    await build(tools, MemoryJournal(), InMemorySaver()).ainvoke({"input": PAYLOAD}, config("u20"), durability="sync")
    assert len(tools.calls) == 1 and waits == [], (tools.calls, waits)


async def test_a_retry_waits_at_least_as_long_as_the_system_asked(waits: list[float]) -> None:
    tools = ScriptedTools("read", [raised("rate_limited", retry_after=40.0), raised("rate_limited", retry_after=40.0)])
    await build(tools, MemoryJournal(), InMemorySaver()).ainvoke({"input": PAYLOAD}, config("u21"), durability="sync")
    # The read's own waits are 5 s and 30 s; the system's retry-after of 40 s is the floor of each.
    assert len(tools.calls) == 3 and waits == [40.0, 40.0], waits


async def test_a_slow_step_stops_retrying_at_its_total_duration(
    waits: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [0.0]
    monkeypatch.setattr("ops_engine.compiler.monotonic", lambda: now[0])

    class Slow(ScriptedTools):
        async def call(
            self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
        ) -> ToolResult:
            now[0] += 500.0  # each call takes 500 s before it fails
            return await super().call(operation, input, key, generation, token)

    tools = Slow("read", [raised("app_unavailable")] * 3)
    await build(tools, MemoryJournal(), InMemorySaver()).ainvoke({"input": PAYLOAD}, config("u22"), durability="sync")
    # A read may take 900 s in all: a third attempt would begin past it.
    assert len(tools.calls) == 2, tools.calls
