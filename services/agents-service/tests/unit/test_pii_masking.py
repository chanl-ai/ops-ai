"""Masking personal data in what an agent's turn shows, by failure mode: an SSN, its last
four, a card or account number, an email or a phone reaches a reply, a stored message, a step's output or a citation;
a number streamed across two chunks shows its first half unmasked; an amount, a date or a case number is masked by
mistake; the model stops seeing the real value, so a turn cannot chain on it; the setting off still masks; a value
named as an SSN, account, card or tax id (ssnLast4 "4471", accountIds ["CHQ-1003"], a number-typed account) passes
because no pattern finds it in the value alone; a field that only mentions an account or a card (a count, a name, chat's
own cards) is masked by mistake."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from ops_agent_kernel.contract import ModelEndpoint
from ops_agent_kernel.events import CitationsReady, KernelEvent, TextDelta, TextReplaced, ToolOutput, TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.pii import StreamMasker, mask
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.testing import Answer, Reply, ToolCall
from ops_agent_kernel.types import AgentSettings, Passage, PromptFragment, ToolGrant, TurnRequest
from ops_pii import masked
from ops_service_kit.http import Json
from tests.conftest import model_on, returned

READ = ToolGrant(
    "get_customer",
    "Core banking",
    "Read a customer",
    "read",
    {"type": "object", "properties": {"id": {"type": "string"}}},
)
RECORD = {
    "name": "Ann Lee",
    "ssn": "123-45-6789",
    "email": "ann.lee@example.com",
    "account": "4401235567",
    # The fake bank's own field names: no pattern finds a last four or a lettered account id in the value alone.
    "ssnLast4": "4471",
    "accountIds": ["CHQ-1003", "BUS-7781"],
}
REPLY = "Ann Lee, SSN ending 6789, email ann.lee@example.com, phone (902) 555-0147, account 4401235567."


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("SSN 123-45-6789", "SSN [SSN]"),
        ("her SSN ending 6789", "her SSN ending ••••"),
        ("social security number 6789", "social security number ••••"),
        ("write to ann.lee@example.com today", "write to [email] today"),
        ("call (902) 555-0147 or +1 902-555-0147", "call [phone] or [phone]"),
        ("card 4111 1111 1111 1111", "card [card]"),
        ("card ending 4410", "card ending ••••"),
        ("account 4401235567", "account ••••"),
        ("ref 4401235567", "ref [account]"),
    ],
)
def test_each_kind_of_personal_data_is_masked(text: str, shown: str) -> None:
    assert mask(text) == shown


@pytest.mark.parametrize(
    "text",
    [
        "a levy of 3,250.00 CAD",
        "served 2026-10-14",
        "case NS-2026-GN-01187",
        # A Salesforce case number is eight digits; named as a case it read as "[account]" in a prep brief.
        "Case 00045120: Update the beneficiary",
        "case number 00045120",
        "Ticket #00045120 and order no. 1234567890",
        "wire W-88213",
        "page 1 of 3, in 2026",
        # Ids carry digit runs glued to letters (uc-233: a run's file id came back as fil_13cf059e[account]...).
        "fil_13cf059e9367473281ca9d7d61f8d116",
        "wfrun_273808292bd7",
        "doc 4f1234567890123456ab",
        # Prose about a field, and a field with no value, are not values.
        "The account number is required before the card id can be checked.",
        '{"accountId": null, "cardNumber": true}',
        "1 of 12 items, total 1100",
        # A heading or a sentence naming an account or a card alone, then a word that is not its value.
        "| Customer | Account | Balance |",
        "Here is the account: it has three holds.",
    ],
)
def test_amounts_dates_case_numbers_and_ids_are_not_masked(text: str) -> None:
    assert mask(text) == text


@pytest.mark.parametrize(
    ("key", "value", "shown"),
    [
        ("ssnLast4", "4471", "[SSN]"),
        ("ssn_last4", 4471, "[SSN]"),
        ("SSN", 123456789, "[SSN]"),
        ("accountId", "BUS-7781", "[account]"),
        ("account_id", 77810042, "[account]"),
        ("accountIds", ["CHQ-1003", 4410], ["[account]", "[account]"]),
        ("accountNumber", 4401235567.0, "[account]"),
        ("account_number", "4401235567", "[account]"),
        ("cardLast4", "5521", "[card]"),
        ("card_last4", 5521, "[card]"),
        ("cardNumber", 4111111111111111, "[card]"),
        ("taxId", "98-7654321", "[tax ID]"),
        ("tax_id", 987654321, "[tax ID]"),
        ("taxpayerIdLast4", "4321", "[tax ID]"),
        # Named by the account or card alone, or by a reference word, and in lower case with no word break.
        ("account", "CHQ-2219", "[account]"),
        ("bankAccount", 4401235567, "[account]"),
        ("debitCard", "5521", "[card]"),
        ("iban", "GB33BUKB20201555555555", "[account]"),
        ("accountRef", "ACME", "[account]"),
        ("card_token", "tok_9f2a", "[card]"),
        ("accountid", "SAVINGS-2219", "[account]"),
        ("ssnlast4", "4471", "[SSN]"),
        # Which account a connection uses (team, own) is readable only under the bare name: an id is still an id.
        ("accountId", "team", "[account]"),
        ("account", "SAVINGS", "[account]"),
    ],
)
def test_a_value_is_masked_by_its_field_name_whatever_its_type(key: str, value: Any, shown: Any) -> None:
    assert masked({"customer": {key: value}}) == {"customer": {key: shown}}
    # A field drawn as a labelled row ({label, value}) is named by its label.
    label = " ".join(key.replace("_", " ").split())
    assert masked([{"label": label, "value": value}]) == [{"label": label, "value": shown}]


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ('{"ssnLast4": "4471", "name": "Ann"}', '{"ssnLast4": "[SSN]", "name": "Ann"}'),
        ("{'accountId': 'BUS-7781', 'document': 'ID'}", "{'accountId': '[account]', 'document': 'ID'}"),
        ('{"accountNumber": 4401, "card_last4": 5521}', '{"accountNumber": "[account]", "card_last4": "[card]"}'),
        ("Account id BUS-7781; Document proof", "Account id [account]; Document proof"),
        ('{"accountIds": ["CHQ-1003", "BUS-7781"]}', '{"accountIds": ["[account]", "[account]"]}'),
        ("Tax ID 98-7654321 was filed", "Tax ID [tax ID] was filed"),
        ("SSN: 123-45-6789 on file", "SSN: [SSN] on file"),
        ("accountId=BUS-7781 card_number: 4111 1111 1111 1111", "accountId=[account] card_number: [card]"),
        # A value with more than six letters, with no digit at all, or after a field name with no separator.
        ("Account ID: SAVINGS-2219 on file", "Account ID: [account] on file"),
        ("accountId: ABCDEFG", "accountId: [account]"),
        ("place_hold: account_id CHQ-2219, reason fraud", "place_hold: account_id [account], reason fraud"),
        # A table, a tab, an arrow, XML and a quoted name with a space in it.
        ("| Account ID | SAVINGS-2219 |", "| Account ID | [account] |"),
        ("Account ID\tSAVINGS-2219", "Account ID\t[account]"),
        ("accountId -> BUS-7781", "accountId -> [account]"),
        ("<accountId>BUS-7781</accountId>", "<accountId>[account]</accountId>"),
        ('{"Account ID": "SAVINGS-2219"}', '{"Account ID": "[account]"}'),
    ],
)
def test_a_field_named_in_text_is_masked_by_its_name(text: str, shown: str) -> None:
    assert mask(text) == shown
    # Streamed after more than HOLD characters, the name and its value are released together wherever it is cut.
    said = f"The bank returned this for the customer: {text} and nothing else was on file today."
    for cut in range(1, len(said)):
        stream = StreamMasker()
        assert stream.push(said[:cut]) + stream.push(said[cut:]) + stream.flush() == mask(said), cut
    assert mask(said) == f"The bank returned this for the customer: {shown} and nothing else was on file today."


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("accountName", "Acme Lending"),
        ("account_holder", "Ann Lee"),
        ("accountCount", 3),
        ("accounts", 2),
        ("tax", 13.0),
        ("card_limit", 5000),
        ("ssnVerified", True),
        ("ssnLast4", None),
        ("amount", 1250000),
        ("cards", [{"type": "case", "id": "cas_0001"}]),
        # tools-service's word for which account a connection signs in with.
        ("account", "team"),
        ("account", "own"),
    ],
)
def test_fields_that_name_no_identifier_are_kept(key: str, value: Any) -> None:
    assert masked({key: value}) == {key: value}
    assert masked([{"label": key, "value": value}]) == [{"label": key, "value": value}]
    assert mask(json.dumps({key: value})) == json.dumps({key: value})


def test_an_object_under_a_personal_data_field_has_its_identifiers_masked() -> None:
    # account.{id, number} is the shape a workflow's definition reads; ssn.{last4}; ids keyed by the account's kind.
    value = {
        "account": {"id": "CHQ-2219", "number": 4401235567, "name": "Acme Lending", "balance": 1250.5},
        "ssn": {"last4": "4471"},
        "accountIds": {"checking": "CHQ-1003", "savings": 7781},
    }
    assert masked(value) == {
        "account": {"id": "[account]", "number": "[account]", "name": "Acme Lending", "balance": 1250.5},
        "ssn": {"last4": "[SSN]"},
        "accountIds": {"checking": "[account]", "savings": "[account]"},
    }


@pytest.mark.parametrize("name", ["label", "name", "key", "field"])
def test_a_row_is_named_by_its_name_key_or_field(name: str) -> None:
    rows = [{name: "accountId", "value": "BUS-7781"}, {name: "Customer", "value": "Ann Lee"}]
    assert masked(rows) == [{name: "accountId", "value": "[account]"}, {name: "Customer", "value": "Ann Lee"}]


def test_a_short_value_is_masked_under_its_field_and_not_wherever_its_digits_appear() -> None:
    # A value 1 turned "1 of 12 items, total 1100" into "[account] of [account]2 items, total [account][account]00".
    read = {"accountId": {"value": 1, "citation": {"page": 1, "quote": "1 of 12 items, total 1100"}}}
    assert masked(read) == {
        "accountId": {"value": "[account]", "citation": {"page": 1, "quote": "1 of 12 items, total 1100"}}
    }
    # A quote that is the value itself is still masked.
    assert masked({"accountId": {"value": "BUS-7781", "quote": "BUS-7781"}})["accountId"]["quote"] == "[account]"


@pytest.mark.parametrize("cut", range(1, len(REPLY)))
def test_a_number_split_across_chunks_is_never_shown_in_part(cut: int) -> None:
    stream = StreamMasker()
    shown = stream.push(REPLY[:cut]) + stream.push(REPLY[cut:]) + stream.flush()
    assert shown == mask(REPLY)
    assert "6789" not in shown and "ann.lee" not in shown and "4401235567" not in shown and "555-0147" not in shown


CASE_REPLY = "Grace has an open request about the trust account, see Case 00045120: Update the beneficiary today."


@pytest.mark.parametrize("cut", range(1, len(CASE_REPLY)))
def test_a_case_number_streamed_apart_from_its_word_stays_readable(cut: int) -> None:
    stream = StreamMasker()
    shown = stream.push(CASE_REPLY[:cut]) + stream.push(CASE_REPLY[cut:]) + stream.flush()
    assert shown == CASE_REPLY


class Tools:
    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        return ToolOutcome(True, RECORD)


def turn_model(seen: list[str]) -> ModelEndpoint:
    """Reads the customer, then answers with what it read; `seen` keeps every tool result the model was given."""

    def reply(messages: list[Json], tools: list[Json]) -> Answer:
        results = returned(messages, every=True)
        if not results:
            return Reply(tool_calls=[ToolCall("get_customer", {"id": "C-1001"})])
        seen.extend(json.dumps(r) for r in results)
        return REPLY

    # Small chunks, so numbers and the email arrive split.
    return model_on(reply, chunk=5)


async def turn(redact: bool) -> tuple[list[KernelEvent], list[str]]:
    seen: list[str] = []
    settings = replace(AgentSettings("ag_x", 1, [PromptFragment("You help.")], "test-model"), redact_pii=redact)
    req = TurnRequest("t1", "th1", settings, [READ], user_turn="Who is C-1001?")
    events = [e async for e in run_turn(req, KernelPorts(model=turn_model(seen), tools=Tools(), knowledge=None))]  # type: ignore[arg-type]
    return events, seen


async def test_what_a_turn_shows_is_masked_while_the_model_reads_the_real_values() -> None:
    events, seen = await turn(redact=True)
    streamed = "".join(e.delta for e in events if isinstance(e, TextDelta))
    [output] = [e.call.output for e in events if isinstance(e, ToolOutput)]
    finished = events[-1]
    assert isinstance(finished, TurnFinished)
    assert streamed == mask(REPLY) == finished.result.text
    assert output == {
        "name": "Ann Lee",
        "ssn": "[SSN]",
        "email": "[email]",
        "account": "[account]",
        "ssnLast4": "[SSN]",
        "accountIds": ["[account]", "[account]"],
    }
    assert finished.result.tool_calls[0].output == output
    # The model was given the record as it is, so it can chain on the account id.
    assert any("123-45-6789" in s and "4401235567" in s for s in seen)
    assert not any(isinstance(e, TextReplaced) for e in events)


async def test_with_the_setting_off_nothing_is_masked() -> None:
    events, _ = await turn(redact=False)
    finished = events[-1]
    assert isinstance(finished, TurnFinished) and finished.result.text == REPLY


class Knowledge:
    async def search(self, query: str, kb_ids: list[str]) -> list[Passage]:
        return [
            Passage("doc_1", "Customer notes", "Contact", "1", "Ann Lee, SSN 123-45-6789, ann.lee@example.com.", "kb_1")
        ]


async def test_a_cited_passage_is_masked_where_people_see_it() -> None:
    """Citations carried the passage text unmasked, in the stream and in the stored answer."""

    settings = replace(AgentSettings("ag_x", 1, [PromptFragment("You help.")], "test-model"), redact_pii=True)
    req = TurnRequest("t2", "th2", settings, [], user_turn="Who is Ann?", kb_ids=["kb_1"])
    cited = model_on(lambda messages, tools: "Ann's details are on file [1].", chunk=100)
    ports = KernelPorts(model=cited, tools=Tools(), knowledge=Knowledge())  # type: ignore[arg-type]
    events = [e async for e in run_turn(req, ports)]
    [ready] = [e for e in events if isinstance(e, CitationsReady)]
    finished = events[-1]
    assert isinstance(finished, TurnFinished)
    for cited in (ready.citations, finished.result.citations):
        assert [c.passage.text for c in cited] == ["Ann Lee, SSN [SSN], [email]."], cited
