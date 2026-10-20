"""present with an agent's widgets and composed layouts (c-082, `.codeloop/wiki/concepts/chat-widgets.md`), by
failure mode: a widget outside the agent's list, data that misses its template's fields, a layout from an agent that
may not compose, a layout with something outside the catalogue (an event handler, an image, an unknown primitive), a
layout past the size limits, and more widgets in one answer than the agent allows."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from ops_agent_kernel import present
from ops_agent_kernel.ports import KernelPorts
from ops_agent_kernel.types import AgentSettings, TurnRequest, WidgetTemplate
from tests.conftest import looping_model
from tests.unit.test_kernel import SETTINGS, FixedKnowledge, RecordingTools, ports, run

HOLD_REVIEW = WidgetTemplate(
    widget_id="hold-review",
    version=3,
    name="Hold review",
    use_when="A payment hold is being discussed and the person needs its amount and reason.",
    tree={
        "type": "card",
        "title": {"$bind": "/payee"},
        "children": [
            {"type": "metric", "label": "Held", "value": {"$bind": "/amount"}, "unit": {"$bind": "/currency"}},
            {"type": "badge", "text": {"$bind": "/status"}, "tones": {"held": "warning", "released": "success"}},
            {
                "type": "button",
                "label": "Release hold",
                "reply": {"text": "Release this hold.", "values": {"holdId": {"$bind": "/holdId"}}},
            },
        ],
    },
    schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["holdId", "payee", "amount", "currency", "status"],
        "properties": {
            "holdId": {"type": "string"},
            "payee": {"type": "string"},
            "amount": {"type": "number"},
            "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
            "status": {"type": "string", "enum": ["held", "released"]},
        },
    },
)
HOLD = {"holdId": "hold_204", "payee": "Acme Supplies Ltd", "amount": 12500, "currency": "GBP", "status": "held"}
WITH_WIDGETS = replace(SETTINGS, widgets=[HOLD_REVIEW])
COMPOSING = replace(SETTINGS, compose=True)


async def _present(settings: AgentSettings, *calls: dict[str, Any]) -> list[Any]:
    """One turn per call (the scripted model makes one call a turn); the records in order."""
    out: list[Any] = []
    for args in calls:
        req = TurnRequest("t1", "th1", settings, [], user_turn=f"call present {json.dumps(args)}")
        _, result = await run(req, ports(RecordingTools()))
        out.extend(result.tool_calls)
    return out


async def test_the_model_fills_one_of_the_agents_widgets() -> None:
    (rec,) = await _present(WITH_WIDGETS, {"widget": "hold-review", "data": HOLD})
    assert rec.status == "ok", rec.output
    part = rec.view["part"]
    assert part["template"] == {"id": "hold-review", "version": 3, "name": "Hold review"}
    card = part["layout"]
    assert card["title"] == "Acme Supplies Ltd"
    metric, badge, button = card["children"]
    assert (metric["value"], metric["unit"]) == (12500, "GBP")
    assert badge == {"type": "badge", "text": "held", "tone": "warning"}, "the tones lookup picks the tone"
    assert button["reply"] == {"text": "Release this hold.", "values": {"holdId": "hold_204"}}


async def test_a_widget_outside_the_agents_list_is_refused() -> None:
    (rec,) = await _present(WITH_WIDGETS, {"widget": "case-summary", "data": HOLD})
    assert rec.status == "error" and rec.view is None
    assert "hold-review" in str(rec.output), "the refusal names the widgets the agent has"


async def test_data_missing_a_field_is_refused_with_the_widgets_fields() -> None:
    (rec,) = await _present(WITH_WIDGETS, {"widget": "hold-review", "data": {**HOLD, "currency": "pounds"}})
    assert rec.status == "error" and rec.view is None
    assert "/currency" in str(rec.output) and "payee (string, required)" in str(rec.output)


async def test_an_agent_that_may_not_compose_cannot_send_a_layout() -> None:
    (rec,) = await _present(WITH_WIDGETS, {"layout": {"type": "text", "text": "hi"}})
    assert rec.status == "error" and "may not compose" in str(rec.output)


async def test_a_composed_layout_from_catalogue_primitives_is_shown() -> None:
    tree = {
        "type": "card",
        "title": "Open holds",
        "children": [{"type": "keyValue", "items": [{"label": "Count", "value": 2}]}],
    }
    (rec,) = await _present(COMPOSING, {"layout": tree})
    assert rec.status == "ok" and rec.view["part"] == {"type": "widget", "id": "", "layout": tree}


async def test_a_composed_layout_with_anything_outside_the_catalogue_draws_nothing() -> None:
    """An injected tool result asking the model to draw a fake approval or a tracking image gets nowhere."""
    bad = [
        {"type": "button", "label": "Approve", "reply": {"text": "ok"}, "onClick": "fetch('//evil')"},
        {"type": "image", "alt": "chart", "src": "https://evil.example/pixel.png"},
        {"type": "html", "text": "<button>Approve</button>"},
        {"type": "text", "text": {"$bind": "/secret"}},
        {"type": "card", "children": [{"type": "text", "text": "x"}] * 51},
    ]
    recs = await _present(COMPOSING, *({"layout": t} for t in bad))
    assert [r.status for r in recs] == ["error"] * len(bad), [r.output for r in recs]
    assert all(r.view is None for r in recs)


async def test_an_answer_shows_no_more_widgets_than_the_agent_allows() -> None:
    """A model that keeps presenting (looping_model calls present every step, whatever it is told) shows one widget, is
    refused once and told to answer in text, and the turn ends at its next call instead of running to the step limit."""
    capped = replace(SETTINGS, max_steps=8, widgets_per_turn=1)
    req = TurnRequest("t1", "th1", capped, [], user_turn="compare")
    model = KernelPorts(model=looping_model(), tools=RecordingTools(), knowledge=FixedKnowledge([]))
    _, result = await run(req, model)
    # Shown, refused for the cap, then stopped at the very next call.
    assert [r.status for r in result.tool_calls] == ["ok", "error", "error"], [r.status for r in result.tool_calls]
    assert "answer in text" in str(result.tool_calls[1].output)
    assert result.status == "completed" and result.stop_reason == "final", result.stop_reason
    assert "step limit" not in result.text, "the turn ended with what it showed, not at the step limit"


def test_an_agent_with_no_widgets_keeps_todays_present_tool() -> None:
    assert present.grant(SETTINGS) is present.PRESENT
    g = present.grant(replace(WITH_WIDGETS, compose=True))
    assert g.input_schema["properties"]["widget"]["enum"] == ["hold-review"]
    assert "hold-review: A payment hold is being discussed" in g.description, (
        "the widget's use-when is the implicit skill"
    )
    assert "layout" in g.input_schema["properties"] and "required" not in g.input_schema


async def test_a_composed_button_needing_a_tool_the_turn_lacks_is_refused() -> None:
    """A model cannot offer an action the agent cannot take: a button whose `requires` names an ungranted tool."""
    tree = {"type": "button", "label": "Release", "requires": "release_hold", "reply": {"text": "Release it."}}
    (rec,) = await _present(COMPOSING, {"layout": tree})
    assert rec.status == "error" and "release_hold" in str(rec.output) and rec.view is None
