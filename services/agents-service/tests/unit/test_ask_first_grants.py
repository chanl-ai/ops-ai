"""Which of a turn's write grants pause to ask the person in chat first (agent_wrapper.ask_first), by failure mode:

- a write of an app whose "Ask before changes" is on runs without asking the person in the chat;
- a turn with nobody in it (a workflow's or a schedule's agent) is asked, where it keeps today's behaviour;
- a test turn on an app with a test account asks, though that write changes nothing real;
- an app the person allowed for this chat asks again in the same chat;
- a read asks before it runs.
"""

from __future__ import annotations

from ops_agent_kernel.types import ToolGrant
from ops_agents.activities.tool_directory import OperationRef
from ops_agents.graphs.agent_wrapper import ask_first


def _op(name: str, access: str = "write", *, asks: bool = True, held: bool = False, test: bool = False) -> OperationRef:
    return OperationRef(
        name=name, description=name, access=access, input_schema={}, requires_approval=held, module_id="mod_desk",
        module_name="Desk", asks_first=asks, test_account=test,
    )  # fmt: skip


def _grant(op: OperationRef) -> ToolGrant:
    return op.grant()


OPS = [_op("update_ticket"), _op("find_ticket", "read", asks=False), _op("refund", held=True)]


def test_a_write_of_an_app_that_asks_pauses_for_the_person_in_chat() -> None:
    out = {g.name: g for g in ask_first([_grant(o) for o in OPS], OPS, person="p@bank.example", live=True, allowed=[])}
    assert out["update_ticket"].gated, out["update_ticket"]
    assert not out["find_ticket"].gated


def test_a_turn_with_nobody_in_it_is_not_asked() -> None:
    out = ask_first([_grant(o) for o in OPS], OPS, person=None, live=True, allowed=[])
    assert not next(g for g in out if g.name == "update_ticket").gated


def test_a_test_turn_on_an_app_with_a_test_account_is_not_asked_and_one_without_is() -> None:
    tested = [_op("update_ticket", test=True)]
    assert not ask_first([_grant(o) for o in tested], tested, person="p@bank.example", live=False, allowed=[])[0].gated
    assert ask_first([_grant(o) for o in OPS[:1]], OPS[:1], person="p@bank.example", live=False, allowed=[])[0].gated


def test_an_app_allowed_for_this_chat_is_not_asked_again() -> None:
    out = ask_first([_grant(o) for o in OPS[:1]], OPS[:1], person="p@bank.example", live=True, allowed=["mod_desk"])
    assert not out[0].gated
