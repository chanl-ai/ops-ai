"""Whose login an app call ran as reaches the chat, by failure mode: a call on an app everyone uses with the team's
login shows no line saying who acted, because the gateway's answer is dropped between the tool executor, the turn's
call record, the run's event and the chat message."""

from __future__ import annotations

from typing import Any

from ops_agent_kernel.ports import KernelPorts
from ops_agent_kernel.testing import Reply, ToolCall
from ops_agent_kernel.types import TurnRequest
from ops_agents.activities.catalog import load_catalog
from ops_agents.activities.gateway import GatewayToolExecutor
from ops_agents.api.chat_threads import AssistantBuilder
from ops_agents.graphs.common import _call_data as call_data  # pyright: ignore[reportPrivateUsage]
from ops_contracts.chat import ChatMessage, ToolEndEvent
from tests.conftest import SEED
from tests.unit.test_kernel import SETTINGS, FixedKnowledge, run
from tests.unit.test_model_told_plainly import QUERY, RECORDS, Gateway, model

SIGNED = {"whose": "team", "login": "ops@harborpine.example", "app": "Salesforce"}


async def test_a_team_login_call_carries_who_acted_to_the_chat_card() -> None:
    seen: list[Any] = []
    steps = [Reply(tool_calls=[ToolCall("salesforce_query", {})]), "New."]
    answer = {"ok": True, "output": RECORDS[0], "view": None, "signedIn": SIGNED}
    tools = GatewayToolExecutor(Gateway(answer), None)  # type: ignore[arg-type]
    req = TurnRequest("t1", "th1", SETTINGS, [QUERY], user_turn="status of case 00044818")
    _, result = await run(req, KernelPorts(model=model(steps, seen), tools=tools, knowledge=FixedKnowledge([])))
    builder = AssistantBuilder(load_catalog(SEED), ChatMessage(id="m1", role="assistant", content="", at="t"))
    events = builder.apply("tool_call", call_data(result.tool_calls[0]))
    call = next(e.call for e in events if isinstance(e, ToolEndEvent))
    assert call.signed_in is not None and call.signed_in.model_dump() == SIGNED, call
