"""An approval card filled from what the model sent: an input it left out (a hold's reason) shows as nothing, never as
the template's `{reason}`, and a row with nothing to show is left off the card."""

from __future__ import annotations

from ops_agents.activities.catalog import load_catalog
from ops_agents.activities.tools import fill
from ops_agents.api.chat_threads import AssistantBuilder
from ops_contracts.chat import ApprovalWidget, ChatMessage, WidgetEvent
from tests.conftest import SEED


def test_a_placeholder_with_no_value_is_left_empty() -> None:
    assert fill("Hold {amount} for {reason}", {"amount": "3250"}) == "Hold 3250 for "


def test_a_hold_with_no_reason_shows_no_placeholder_and_no_empty_row() -> None:
    builder = AssistantBuilder(load_catalog(SEED), ChatMessage(id="m1", role="assistant", content="", at="t"))
    payload = {"tool": "place_hold", "input": {"account_id": "CHQ-2219", "amount": 3250}, "review_id": "r1"}
    events = builder.apply("waiting_review", {"id": "i1", "payload": payload})
    card = next(e.widget for e in events if isinstance(e, WidgetEvent))
    assert isinstance(card, ApprovalWidget)
    shown = [card.title, card.summary, card.action, *(f.value for f in card.fields)]
    assert not any("{" in s for s in shown), shown
    assert all(f.value.strip() for f in card.fields), card.fields
