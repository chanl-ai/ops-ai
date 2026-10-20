"""The workflows a service event starts by default (c-258). They are ordinary workflow definitions, kept in the
service's `seed/event_workflows.json`, which ships in every environment (the image holds the services tree): each
tenant gets them, live and owned by no team, when its first event
arrives (service_events.ensure_event_workflows), and from then on they are edited, versioned and published through
review like any other workflow, and run by hand by anyone `can()` lets run workflows.

Each one's Service event trigger names the event it handles, and the tenant's no-team workflow under that id is the
event's one handler. A team's workflow with the same trigger is never started by the event, so a builder cannot take
over a reaction by copying it: tool_access_request decides who gets a tool module (its review step's notDecidedBy keeps
the requester out, and tools-service refuses a decision by the requester), system_extract saves what a person asked to
read from a file, and file_deleted_purge removes what was read from a deleted file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

EVENT_TRIGGER = "ops.trigger.event"

SEED_FILE = Path(__file__).resolve().parents[3] / "seed" / "event_workflows.json"
EVENT_WORKFLOWS: list[dict[str, Any]] = json.loads(SEED_FILE.read_text())


def event_of(definition: dict[str, Any]) -> str | None:
    """The event a definition's Service event trigger names, if it has one."""
    for node in cast(list[dict[str, Any]], definition.get("nodes") or []):
        if node.get("type") == EVENT_TRIGGER:
            return str(cast(dict[str, Any], node.get("parameters") or {}).get("event") or "") or None
    return None


def handlers(items: list[dict[str, Any]]) -> dict[str, str]:
    """Each event to the id of the workflow that handles it."""
    return {event: str(item["id"]) for item in items if (event := event_of(item))}
