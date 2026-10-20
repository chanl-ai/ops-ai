"""A v2 review is keyed by its step, so two review steps of one run are two reviews, and an option named reject
shows as rejected."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from ops_agents.api import engine_reviews
from ops_service_kit.errors import ValidationFailed

RUN: dict[str, Any] = {"id": "wfrun_1", "workflow_id": "w", "updated_at": "now", "waiting": None}
# Named, so the view reads no definition.
TITLES: dict[str, Any] = {"workflow": "w", "steps": {}}


def decided(node: str, option: str) -> dict[str, Any]:
    payload = {"node": node, "step_id": f"wfrun_1:{node}:1", "options": [{"name": "hold"}, {"name": "reject"}]}
    return {"payload": payload, "resume": {"decision": "approved", "option": option}, "at": "now"}


async def test_two_review_steps_are_two_reviews_and_reject_is_rejected() -> None:
    rt: Any = SimpleNamespace()
    # The case is named, so the view reads no database.
    first = await engine_reviews.view(rt, RUN, decided("check", "hold"), case_id="case_1", titles=TITLES)
    second = await engine_reviews.view(rt, RUN, decided("confirm", "reject"), case_id="case_1", titles=TITLES)
    assert (first["id"], second["id"]) == ("wfrun_1:check:1", "wfrun_1:confirm:1")
    assert (first["status"], second["status"]) == ("approved", "rejected")
    assert engine_reviews.run_of(second["id"]) == "wfrun_1"
    assert (first["caseId"], second["caseId"]) == ("case_1", "case_1")


async def test_a_step_no_model_scored_has_no_confidence() -> None:
    rt: Any = SimpleNamespace()
    review = await engine_reviews.view(rt, RUN, decided("check", "hold"), case_id="case_1", titles=TITLES)
    assert review["confidence"] is None


LEVY_DRAFT: dict[str, Any] = {
    "record": {"name": "Marcus Bell", "amount": 3250.0, "case_no": "NS-2026-GN-01187"},
    "customer": {"id": "CUS-1001", "name": "Marcus Bell"},
    "accounts": [
        {"id": "CHQ-2219", "currency": "CAD", "balance": 2140.55},
        {"id": "SAV-4410", "currency": "CAD", "balance": 18250.0},
    ],
}
LEVY_CALLS: list[dict[str, Any]] = [
    {"tool": "place_hold", "input": {"account_id": "CHQ-2219", "amount": 3250.0, "reason": "NS-2026-GN-01187"}},
    {"tool": "add_customer_note", "input": {"customer_id": "CUS-1001", "text": "Levy notice received."}},
]


def test_a_levy_review_row_names_the_customer_the_amount_and_the_accounts_currency() -> None:
    # The row showed an empty customer, no amount, USD for a CAD account and the draft as a Python dict string.
    typed = engine_reviews.typed_fields(LEVY_DRAFT, LEVY_CALLS)
    assert (typed["customer"], typed["amount"], typed["currency"]) == ("Marcus Bell", 3250.0, "CAD")
    assert typed["proposal"] == "place_hold: account_id CHQ-2219, amount 3250.0, reason NS-2026-GN-01187"


def test_a_review_with_no_customer_or_amount_leaves_them_empty_and_shows_a_text_draft_as_it_is() -> None:
    typed = engine_reviews.typed_fields("Check the debtors read from the document.", [])
    text = "Check the debtors read from the document."
    assert typed == {"customer": "", "amount": None, "currency": None, "proposal": text}


PAUSED: dict[str, Any] = {
    "editable": {"path": "$.nodes.read.out.records", "value": [{"values": {"name": "A", "amount": 1.0}}]}
}


def test_a_correction_keeps_to_the_reads_fields() -> None:
    fixed = [{"values": {"name": "A", "amount": 2.0}}]
    assert engine_reviews.correction(PAUSED, {"edited": fixed, "amount": 5}) == (fixed, {"amount": 5})
    assert engine_reviews.correction(PAUSED, None)[0] is engine_reviews.NOTHING
    with pytest.raises(ValidationFailed, match="ssn"):
        engine_reviews.correction(PAUSED, {"edited": [{"values": {"name": "A", "ssn": "1"}}]})
    with pytest.raises(ValidationFailed, match="nothing to correct"):
        engine_reviews.correction({}, {"edited": []})


def test_a_review_counts_down_to_its_own_deadline_or_the_workspaces() -> None:
    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    own = engine_reviews.review_deadline(
        {"openedAt": "2026-10-18T11:00:00.000Z", "slaHours": 2, "onTimeout": "expire"}, 8.0, now
    )
    assert own == {
        "sla": "2h",
        "onTimeout": "Expires: takes the timeout path",
        "dueAt": "2026-10-18T13:00:00.000Z",
        "minutes": 60,
    }
    workspace = engine_reviews.review_deadline({"openedAt": "2026-10-18T03:00:00.000Z"}, 8.0, now)
    assert (workspace["sla"], workspace["minutes"], workspace["onTimeout"]) == (
        "8h (workspace)",
        -60,
        "Stays open, shows overdue",
    )
    # Paused before deadlines were recorded: no countdown rather than a made-up one.
    assert engine_reviews.review_deadline({}, 8.0, now)["minutes"] is None
