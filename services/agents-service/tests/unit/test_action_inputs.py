"""A person-format action input is checked as an email address before the action runs."""

from __future__ import annotations

import pytest

from ops_agents.api.engine_reviews import _action_inputs  # pyright: ignore[reportPrivateUsage]
from ops_service_kit.errors import ValidationFailed

ACTION = {"inputs": [{"name": "assignee", "format": "person"}]}


def test_person_input_accepts_an_email_and_refuses_a_non_email() -> None:
    assert _action_inputs(ACTION, {"assignee": "case.lead@harborpine.example"}) == {
        "assignee": "case.lead@harborpine.example"
    }
    with pytest.raises(ValidationFailed):
        _action_inputs(ACTION, {"assignee": "not an email"})
