"""Which of a turn's write grants still pause for the person in chat (agent_wrapper.ask_first), by failure mode.
The wait is the tool's own `requiresApproval`; ask_first only lifts it where the person need not answer:

- a write the tool says waits stays held, so the chat draws its card;
- a write that does not wait is never held;
- a turn with nobody in it (a workflow's or a schedule's agent) keeps its grants as they are;
- a test turn on an app with a test account is not held, and a live turn or an app without one is;
- an app the person allowed for this chat is not held again in the same chat, and another app still is.
"""

from __future__ import annotations

from ops_agent_kernel.types import ToolGrant
from ops_agents.activities.tool_directory import OperationRef
from ops_agents.graphs.agent_wrapper import ask_first


def _op(
    name: str, access: str = "write", *, waits: bool = True, test: bool = False, module: str = "mod_desk"
) -> OperationRef:
    return OperationRef(
        name=name, description=name, access=access, input_schema={}, requires_approval=waits, module_id=module,
        module_name="Desk", test_account=test,
    )  # fmt: skip


def _grant(op: OperationRef) -> ToolGrant:
    return op.grant()


OPS = [_op("update_ticket"), _op("find_ticket", "read", waits=False), _op("refund", waits=False)]
ME = "p@bank.example"


def test_a_write_the_tool_says_waits_stays_held_and_one_that_does_not_is_not() -> None:
    out = {g.name: g for g in ask_first([_grant(o) for o in OPS], OPS, person=ME, live=True, allowed=[])}
    assert out["update_ticket"].gated, out["update_ticket"]
    assert not out["find_ticket"].gated and not out["refund"].gated


def test_a_turn_with_nobody_in_it_keeps_its_grants() -> None:
    out = ask_first([_grant(o) for o in OPS], OPS, person=None, live=True, allowed=[])
    assert next(g for g in out if g.name == "update_ticket").gated


def test_a_test_turn_on_an_app_with_a_test_account_is_not_held_and_one_without_is() -> None:
    tested = [_op("update_ticket", test=True)]
    assert not ask_first([_grant(o) for o in tested], tested, person=ME, live=False, allowed=[])[0].gated
    assert ask_first([_grant(o) for o in tested], tested, person=ME, live=True, allowed=[])[0].gated
    assert ask_first([_grant(o) for o in OPS[:1]], OPS[:1], person=ME, live=False, allowed=[])[0].gated


def test_an_app_allowed_for_this_chat_is_not_held_again_and_another_app_is() -> None:
    ops = [_op("update_ticket"), _op("post_invoice", module="mod_books")]
    out = ask_first([_grant(o) for o in ops], ops, person=ME, live=True, allowed=["mod_desk"])
    assert [g.gated for g in out] == [False, True]
