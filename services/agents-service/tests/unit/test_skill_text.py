"""A skill written as text, read into steps and run by the kernel, by failure mode: the end of an `if` block falling
into its `else`; an `if` nested inside an `else` jumping to the wrong step; a mention inside a condition becoming a
step or being checked; a path the agent decides taken on the model's silence, or counted as a failed check that holds
tools; a guard written as `if not <rule>:` letting a missing value through; and a skill saved as a list of steps not
reading back to the same steps."""

from __future__ import annotations

from typing import Any

from ops_agent_kernel import step_tools, steps
from ops_agent_kernel.types import Skill
from ops_agents.app.skill_text import read, render
from ops_contracts.skill_run import SkillProgram, SkillRunState

RETAIL = """Greet them and ask for the email or order number they used.
Look them up with @tool:find_customer
if found:
    Confirm their name and read the last order from @tool:order_history
    if they want a refund:
        Follow @knowledge:refund_policy, then use @tool:issue_refund
    else:
        Answer from @knowledge:help_center
else:
    Ask for the email they used at checkout.
    if @agent:fraud_desk flagged the account:
        stop "Possible fraud"
    else:
        if they gave another email:
            Look again with @tool:find_customer
Thank them."""
FIELDS: dict[str, Any] = {"@tool:find_customer": {"found": {"type": "boolean"}}}


def _skill(program: SkillProgram | None) -> Skill:
    assert program is not None
    return Skill(
        "sk_lookup", 1, "Customer lookup", "customer-lookup", "Find a customer.", "on_match", "", program=program
    )


def _done(run: SkillRunState, holds: bool | None = None) -> SkillRunState:
    moved = step_tools.handle(step_tools.STEP_DONE, run, [], {} if holds is None else {"holds": holds})
    assert moved.ok, moved.said
    return moved.run


def test_paths_compile_to_forward_jumps_and_a_mention_in_a_condition_stays_words() -> None:
    r = read(RETAIL, fields=FIELDS)
    p = r.program
    assert p is not None
    tools = [s.use.id if s.use else None for s in p.steps]
    assert tools == ["find_customer", "order_history", "issue_refund", None, None, None, "find_customer", None]
    found, refund, issue, answer, ask, extra_email = (
        p.steps[0],
        p.steps[1],
        p.steps[2],
        p.steps[3],
        p.steps[4],
        p.steps[5],
    )
    # if found: checked on the result; when it does not hold, the else block starts at step 5.
    assert found.branch and (found.branch.test.text, found.branch.test.by) == ("result.found == true", "rule")
    assert found.branch.otherwise.step == 5
    # The end of each if block skips its else and goes to "Thank them." (step 8).
    assert refund.branch and refund.branch.test.by == "model" and refund.branch.otherwise.step == 4
    assert issue.next and issue.next.step == 8 and answer.next and answer.next.step == 8
    # The nested if inside the else: the mention is words the agent decides, never a step of its own.
    assert ask.use is None and ask.branch and ask.branch.test.by == "model"
    assert "@agent:fraud_desk" in ask.branch.test.text and ask.branch.otherwise.step == 6
    assert ask.next and ask.next.exit == "possible_fraud" and p.exit == {"possible_fraud": "Possible fraud"}
    assert extra_email.branch and extra_email.branch.otherwise.step == 8
    assert any(h["line"] == 11 and "mention in a condition" in h["message"] for h in r.hints), r.hints
    hows = {m["line"]: m["how"] for m in r.marks if m["kind"] == "if"}
    assert hows == {3: "checked", 5: "agent", 11: "agent", 14: "agent"}
    assert r.uses == {"tools": 3, "knowledge": 2, "skills": 0, "agents": 1, "workflows": 0}


def test_free_text_reads_as_no_steps_and_a_deleted_mention_is_the_only_error() -> None:
    plain = read("Be warm.\nQuote @knowledge:refund_policy when asked.\nelse:\nNever promise dates.")
    assert plain.program is None and plain.errors == []
    gone = read(RETAIL, fields=FIELDS, missing={"@tool:issue_refund": "Issue refund"})
    assert gone.program is not None, "a deleted mention still saves its steps"
    assert [(e["line"], e["id"]) for e in gone.errors] == [(6, "tool:issue_refund")]


def test_a_path_the_agent_decides_needs_its_verdict_and_takes_the_other_path_without_a_hold() -> None:
    skill = _skill(read(RETAIL, fields=FIELDS).program)
    run = steps.start(SkillRunState(), skill, [skill], by="model")
    run = steps.on_result(run, [skill], {"found": True}, True).run
    assert run.running is not None and run.running.step == 2
    run = steps.on_result(run, [skill], {"orders": []}, True).run
    refused = step_tools.handle(step_tools.STEP_DONE, run, [skill], {})
    assert not refused.ok and "holds true" in refused.said, "silence is not a verdict"
    run = _done(run, holds=False)
    running = run.running
    assert running is not None and running.step == 4, "no refund: the else path"
    assert running.results["2"].passed is False and running.attempts == {} and run.holds == []
    run = _done(run)
    assert run.running is not None and run.running.step == 8, "the end of the else skips nothing it should run"


def test_a_skill_saved_as_steps_reads_back_as_text_and_its_guard_still_holds() -> None:
    stored = SkillProgram.model_validate(
        {
            "steps": [
                {
                    "do": "Look up the account.",
                    "use": {"kind": "tool", "id": "get_account"},
                    "check": {"text": "result.balance > 0", "by": "rule"},
                    "ifNot": {"action": "exit", "exit": "blocked"},
                },
                {"do": "Place the hold.", "use": {"kind": "tool", "id": "place_hold"}},
            ],
            "exit": {"blocked": "The account is in arrears."},
        }
    )
    text = render("Be brief.", stored)
    back = read(text).program
    assert back is not None
    assert [s.use.id if s.use else None for s in back.steps] == ["get_account", "place_hold"]
    guard = back.steps[0].branch
    assert guard and (guard.test.text, guard.test.by) == ("result.balance > 0", "rule")
    assert guard.otherwise.exit == "blocked" and back.exit == stored.exit
    # The balance is missing: the rule has no answer, so the guard path is taken, as a failed check.
    skill = _skill(back)
    other = Skill("sk_other", 1, "Other", "other", "x", "on_match", "", program=stored)
    run = steps.start(SkillRunState(), skill, [skill, other], by="model")
    run = steps.on_result(run, [skill, other], {"owner": "Ana"}, True).run
    assert run.running is None and run.history[-1].ended == "blocked" and run.history[-1].why == "check"
    assert [h.tools for h in run.holds] == [["place_hold"]]
