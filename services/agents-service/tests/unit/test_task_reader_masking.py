"""A task as a person reads it (`hitl_facade.as_seen_by`), by failure mode: a value under a name kept for every reader
(id, status, kind) is returned raw at any depth, so a tool input's nested SSN or id skips masking; the asker of an
"ask the person" step, its only decider, reads it masked because they hold no `reviews.decide`."""

from __future__ import annotations

import json

from ops_agents.api.auth import Principal
from ops_agents.api.hitl_facade import as_seen_by
from ops_agents.api.run_story import masked_story
from ops_service_kit.http import Json, JsonValue

VIEWER = Principal(
    name="James",
    email="james@harborpine.example",
    team_id="team_ops",
    tenant_id="local",
    team_ids=("team_ops",),
    role="viewer",
    roles={"team_ops": "viewer"},
)


def _task(**extra: JsonValue) -> Json:
    return {
        "id": "thr_1",
        "status": "pending",
        "decidingTeam": {"id": "team_ops", "name": "Ops"},
        "calls": {"hold": {"tool": "place_hold", "input": {"id": "123-45-6789", "status": {"ssn": "123-45-6789"}}}},
        "actionFields": [{"label": "Account", "value": "CHQ-2219"}],
        **extra,
    }


def test_a_name_kept_for_every_reader_is_kept_at_the_top_of_the_task_only() -> None:
    shown = as_seen_by(VIEWER, _task())
    assert "123-45-6789" not in json.dumps(shown) and "CHQ-2219" not in json.dumps(shown), shown
    assert shown["id"] == "thr_1" and shown["status"] == "pending", shown


def test_who_may_decide_a_task_now_reads_its_real_values() -> None:
    # The asker of an ask_first step decides it alone, whatever their roles: canDecide says so.
    shown = as_seen_by(VIEWER, _task(canDecide=True))
    assert "CHQ-2219" in json.dumps(shown) and "123-45-6789" in json.dumps(shown), shown


def test_a_runs_story_masks_a_value_under_a_kept_name_below_its_top() -> None:
    # A step's input keyed status or source is the tool's data, not the story's own state.
    story = {"status": "waiting", "steps": [{"status": {"ssn": "123-45-6789"}, "source": "123-45-6789"}]}
    shown = masked_story(story)
    assert "123-45-6789" not in json.dumps(shown) and shown["status"] == "waiting", shown
