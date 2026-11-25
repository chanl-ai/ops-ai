"""Save-time warnings for a workflow a schedule or an event starts that calls an app each person signs in to.

A run nobody started acts for no one, and the team's login is never a backup for each person (tools-service
auth.Authenticator), so every such run would be refused at that step. The builder is told when saving, with the app
and the two ways on, instead of finding out from the first failed run."""

from __future__ import annotations

from typing import cast

from ops_engine.definition import WorkflowDefinition
from ops_service_kit.http import Json

from ..activities.tool_directory import ToolsUnavailable
from .deps import Runtime

# The triggers that start a run with nobody behind it, in the words the warning uses.
NOBODY_STARTS = {"ops.trigger.schedule": "schedule", "ops.trigger.event": "event"}
TOOL_STEP = "ops.action.tool"
CODE = "each_person_app_unattended"


async def unattended_sign_in_warnings(rt: Runtime, team: str, d: WorkflowDefinition) -> list[Json]:
    """One warning per tool step on an app each person signs in to, when a schedule or an event starts `d`; none
    when tools-service cannot be reached, since a warning never refuses a save."""
    start = next((NOBODY_STARTS[n.type] for n in d.nodes if n.type in NOBODY_STARTS), None)
    steps = [(n.id, str(n.parameters.get("operation") or "")) for n in d.nodes if n.type == TOOL_STEP]
    if start is None or not steps or rt.app_states is None or not team:
        return []
    directory = rt.directory()
    try:
        cards = await rt.app_states.cards(None, team)
        operations = await directory.operations()
    except ToolsUnavailable:
        return []
    finally:
        # The directory keeps a team's list for 30 s, and a run started right after a save must read the operations as
        # they are then (a scope or a review just changed), so a save leaves no list of its own behind.
        if (forget := getattr(directory, "forget", None)) is not None:
            forget()
    each_person = {
        str(m): str(c.get("name") or "")
        for c in cards
        if c.get("signIn") == "person"
        for m in cast(list[str], c.get("moduleIds") or [])
    }
    module_of = {op.name: op.module_id for op in operations}
    out: list[Json] = []
    for node, operation in steps:
        app = each_person.get(str(module_of.get(operation) or ""))
        if app:
            out.append(
                {
                    "node": node,
                    "level": "warning",
                    "code": CODE,
                    "field": "operation",
                    "message": f"{app} signs in as each person, and a {start} starts this workflow with nobody behind "
                    f"it, so this step will be refused. Set {app} to Everyone uses the team's login, or have a person "
                    "start the run.",
                }
            )
    return out
