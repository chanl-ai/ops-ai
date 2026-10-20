"""The fake OpenAI's rule set (scripts/fake_openai), by failure mode: a text rule answering as a tool call, an
`after` rule firing on another tool's result or on another question, and a tool rule firing when the tool is not
offered."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

APP = Path(__file__).resolve().parents[1] / "scripts" / "fake_openai" / "app.py"


def fake() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fake_openai_app", APP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RULES: list[dict[str, Any]] = [
    {"when": "have with us", "tool": "get_customer", "arguments": {"customer_id": "CUS-1002"}},
    {
        "when": "have with us",
        "after": "get_customer",
        "tool": "list_accounts",
        "arguments": {"customer_id": "CUS-1002"},
    },
    {"when": "have with us", "after": "list_accounts", "text": "Priya holds one business chequing account [1]."},
    {"when": "wire transfer", "text": "An outgoing domestic wire costs 30.00 [1]."},
    {"when": "prepayment penalty", "text": "That is not in the knowledge base."},
]
TOOLS = [{"type": "function", "function": {"name": n}} for n in ("get_customer", "list_accounts")]


def script(mod: ModuleType) -> Any:
    return mod.Script([mod.Rule(**r) for r in RULES], ["default"])


def user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def called(tool: str, call_id: str = "c1") -> list[dict[str, Any]]:
    return [
        {
            "role": "assistant",
            "tool_calls": [{"id": call_id, "type": "function", "function": {"name": tool, "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": call_id, "content": "{}"},
    ]


async def test_a_question_chains_reads_and_ends_in_text() -> None:
    mod = fake()
    s = script(mod)
    first = await mod.answer(s, "default", {"messages": [user("What does Priya have with us?")], "tools": TOOLS})
    assert first.tool_calls and first.tool_calls[0]["function"]["name"] == "get_customer"
    msgs = [user("What does Priya have with us?"), *called("get_customer")]
    second = await mod.answer(s, "default", {"messages": msgs, "tools": TOOLS})
    assert second.tool_calls and second.tool_calls[0]["function"]["name"] == "list_accounts"
    msgs += called("list_accounts", "c2")
    third = await mod.answer(s, "default", {"messages": msgs, "tools": TOOLS})
    assert not third.tool_calls and third.text == "Priya holds one business chequing account [1]."


async def test_an_after_rule_needs_its_question_and_its_tool() -> None:
    mod = fake()
    s = script(mod)
    other = [user("What is the fee for a wire transfer?"), *called("get_customer")]
    done = await mod.answer(s, "default", {"messages": other, "tools": TOOLS})
    assert (
        done.tool_calls is None and "[1]" not in (done.text or "")
    ) or done.text != "Priya holds one business chequing account [1]."


async def test_text_rules_answer_with_and_without_tools_offered() -> None:
    mod = fake()
    s = script(mod)
    fee = await mod.answer(s, "default", {"messages": [user("What is the fee for an outgoing wire transfer?")]})
    assert fee.text == "An outgoing domestic wire costs 30.00 [1]." and not fee.tool_calls
    none = await mod.answer(s, "default", {"messages": [user("What is the prepayment penalty?")], "tools": TOOLS})
    assert none.text == "That is not in the knowledge base."


async def test_a_tool_rule_waits_for_its_tool_to_be_offered() -> None:
    mod = fake()
    s = script(mod)
    without = await mod.answer(s, "default", {"messages": [user("What does Priya have with us?")]})
    assert not without.tool_calls and "heard" in (without.text or "")


async def test_a_present_rule_scripts_the_built_in_shaped_answer() -> None:
    """c-055 T021: a rule may call the kernel's present tool when the turn offers it, like any other tool."""
    mod = fake()
    rows = [{"product": "Savings Plus", "rate": 3.1}, {"product": "Money Market", "rate": 3.65}]
    s = mod.Script([mod.Rule(when="compare", tool="present", arguments={"shape": "rows", "data": rows})], ["default"])
    offered = [*TOOLS, {"type": "function", "function": {"name": "present"}}]
    done = await mod.answer(s, "default", {"messages": [user("compare them")], "tools": offered})
    assert done.tool_calls and done.tool_calls[0]["function"]["name"] == "present"
    assert '"shape": "rows"' in done.tool_calls[0]["function"]["arguments"]


DEMO = Path(__file__).resolve().parents[1] / "seed" / "demo-fake-openai"
FEES = (
    "<knowledge>\n[1] Fee Schedule — Transfers and payments (version v1): An outgoing domestic wire transfer costs "
    "30.00. An outgoing international wire transfer costs 45.00. An incoming wire costs 15.00.\n</knowledge>\n\n"
)
COMPARE = (
    "<knowledge>\n[1] Retail Product Sheet — Choosing between Savings Plus and Money Market (version v1): Savings Plus "
    "suits a customer saving for a goal within two years who wants a low entry balance. Money Market suits a customer "
    "holding 25,000 or more who wants the higher tiered rate and unlimited access. A customer with between 5,000 and "
    "25,000 can only open Savings Plus.\n</knowledge>\n\n"
)


def demo_script(mod: ModuleType) -> Any:
    return mod.load_script(DEMO)


async def test_a_cited_answer_needs_its_passage_and_quotes_it() -> None:
    """c-058 T003 (changes requested): a knowledge rule fires only when the passage is in the prompt, and the amounts
    it states come from that passage, not from the rule."""
    mod = fake()
    s = demo_script(mod)
    with_passage = await mod.answer(
        s, "default", {"messages": [user(FEES + "What is the fee for an outgoing wire transfer?")]}
    )
    assert with_passage.text == "An outgoing domestic wire transfer costs 30.00 and an international one 45.00 [1]."
    changed = FEES.replace("30.00", "35.00").replace("45.00", "50.00")
    v2 = await mod.answer(
        s, "default", {"messages": [user(changed + "What is the fee for an outgoing wire transfer?")]}
    )
    assert v2.text == "An outgoing domestic wire transfer costs 35.00 and an international one 50.00 [1].", "quotes v2"
    without = await mod.answer(s, "default", {"messages": [user("What is the fee for an outgoing wire transfer?")]})
    assert "heard" in (without.text or "") and "[1]" not in (without.text or ""), "no passage, no cited answer"


async def test_the_comparison_presents_rows_from_the_passage_then_cites_it() -> None:
    mod = fake()
    s = demo_script(mod)
    offered = [{"type": "function", "function": {"name": "present"}}]
    ask = COMPARE + "Compare Savings Plus and Money Market for her"
    first = await mod.answer(s, "default", {"messages": [user(ask)], "tools": offered})
    assert first.tool_calls and first.tool_calls[0]["function"]["name"] == "present"
    args = json.loads(first.tool_calls[0]["function"]["arguments"])
    assert args["shape"] == "rows" and [r["minimum balance"] for r in args["data"]] == ["5,000", "25,000"]
    msgs = [user(ask), *called("present")]
    second = await mod.answer(s, "default", {"messages": msgs, "tools": offered})
    assert not second.tool_calls and "25,000 or more" in (second.text or "") and "[1]" in (second.text or "")
    bare = await mod.answer(
        s, "default", {"messages": [user("Compare Savings Plus and Money Market for her")], "tools": offered}
    )
    assert not bare.tool_calls and "[1]" not in (bare.text or ""), "no passage, no table and no citation"


async def test_the_customer_answer_quotes_the_tool_result_it_followed() -> None:
    mod = fake()
    s = demo_script(mod)
    tools = [{"type": "function", "function": {"name": n}} for n in ("get_customer", "list_accounts")]
    ask = user("What does Priya Natarajan have with us?")
    profile = {"id": "CUS-1002", "name": "Priya Natarajan", "segment": "small business"}
    asked_customer = called("get_customer", "c1")
    first: list[dict[str, Any]] = [ask, asked_customer[0], {**asked_customer[1], "content": json.dumps(profile)}]
    chained = await mod.answer(s, "default", {"messages": first, "tools": tools})
    assert chained.tool_calls and chained.tool_calls[0]["function"]["name"] == "list_accounts"
    rows: list[dict[str, Any]] = [
        {
            "id": "BUS-7781",
            "customerId": "CUS-1002",
            "type": "business chequing",
            "currency": "CAD",
            "balance": 48210.9,
            "status": "open",
            "holds": [],
        }
    ]
    listed = called("list_accounts", "c2")
    second: list[dict[str, Any]] = [*first, listed[0], {**listed[1], "content": json.dumps(rows)}]
    answered = await mod.answer(s, "default", {"messages": second, "tools": tools})
    assert answered.text == (
        "Priya Natarajan holds one business chequing account, BUS-7781, with a balance of 48210.9 CAD, currently "
        "open, as the bank's records show."
    )
    empty: list[dict[str, Any]] = [*first, listed[0], {**listed[1], "content": "[]"}]
    silent = await mod.answer(s, "default", {"messages": empty, "tools": tools})
    assert "BUS-7781" not in (silent.text or ""), "no account in the result, no account in the answer"


LIMITS = (
    "<knowledge>\n[1] Branch Operations Manual — ATM and debit limits (version v1): "
    "The daily ATM withdrawal limit on a "
    "personal debit card is 1,000. The daily point of sale limit is 3,000. A branch manager can raise either limit for "
    "one day up to double the standard limit when the customer presents photo identification. Interac e-Transfer is "
    "limited to 3,000 a day and 10,000 a week.\n</knowledge>\n\n"
)


async def test_the_atm_limit_presents_the_limits_as_rows_from_the_passage_then_cites_it() -> None:
    """c-058 T003 (uc-079's rows check): the limits table comes from the passage's figures, then the cited sentence;
    without the passage neither appears."""
    mod = fake()
    s = demo_script(mod)
    offered = [{"type": "function", "function": {"name": "present"}}]
    ask = LIMITS + "What is the daily ATM withdrawal limit?"
    first = await mod.answer(s, "default", {"messages": [user(ask)], "tools": offered})
    assert first.tool_calls and first.tool_calls[0]["function"]["name"] == "present"
    args = json.loads(first.tool_calls[0]["function"]["arguments"])
    assert args["shape"] == "rows" and [r["amount"] for r in args["data"]] == ["1,000", "3,000", "3,000", "10,000"]
    second = await mod.answer(s, "default", {"messages": [user(ask), *called("present")], "tools": offered})
    assert (
        not second.tool_calls
        and second.text
        and second.text.startswith("The daily ATM withdrawal limit on a personal debit card is 1,000")
        and "[1]" in second.text
    )
    doubled = LIMITS.replace("is 1,000", "is 2,000")
    other = await mod.answer(
        s, "default", {"messages": [user(doubled + "What is the daily ATM withdrawal limit?")], "tools": offered}
    )
    assert other.tool_calls and json.loads(other.tool_calls[0]["function"]["arguments"])["data"][0]["amount"] == "2,000"
    bare = await mod.answer(
        s, "default", {"messages": [user("What is the daily ATM withdrawal limit?")], "tools": offered}
    )
    assert not bare.tool_calls and "[1]" not in (bare.text or "")
