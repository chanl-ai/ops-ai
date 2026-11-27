"""A turn that breaks reads how its own model replies ended, never how an earlier turn's did.

A paused turn's history keeps the reply that asked for approval. When that reply hit the length limit with its call
still whole, a resumed turn whose approved call then breaks fails as that break, not as reply_cut_off."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.function import FunctionModel

from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.types import Resume, TurnRequest, TurnResult
from tests.unit.test_loop_budget import HOLD, NoKnowledge, Tools, eager, settings


class BrokenTools(Tools):
    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        raise UnexpectedModelBehavior("the gateway sent an unreadable answer")


async def run(req: TurnRequest, model: FunctionModel, tools: Tools | None = None) -> TurnResult:
    ports = KernelPorts(model=model, tools=tools or Tools(), knowledge=NoKnowledge())
    events = [e async for e in run_turn(req, ports)]
    last = events[-1]
    assert isinstance(last, TurnFinished)
    return last.result


async def test_a_resumed_turn_that_breaks_is_not_read_as_the_paused_replys_cut_off() -> None:
    hold = eager(lambda offered, _m: ("place_wire_hold", {"id": "W-1"}) if "place_wire_hold" in offered else None)
    paused = await run(TurnRequest("t1", "th1", settings(4), [HOLD], user_turn="Hold W-1"), hold)
    assert paused.interrupt is not None, paused
    history = json.loads(paused.interrupt.history)
    history[-1]["finish_reason"] = "length"
    interrupt = dataclasses.replace(paused.interrupt, history=json.dumps(history).encode())
    req = TurnRequest("t2", "th1", settings(4), [HOLD], resume=Resume(interrupt, "approved"))
    result = await run(req, hold, BrokenTools())
    assert result.status == "failed" and result.error_code != "reply_cut_off", result
