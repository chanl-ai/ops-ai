"""The Turn on window's "Give the team's assistant this app's read tools", by failure mode: the assistant gets the
app's write tools (other than those its skills name) or another app's tools; the app's skills are not pinned; a second
turn-on makes another version for nothing; someone who may not edit the team's agents changes the assistant; and a
draft someone is editing is stepped over."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ops_agents.activities.tool_directory import OperationRef
from ops_agents.api.agent_registry import registry
from ops_agents.api.ops_tools import ops_assistant_id
from ops_agents.store.tenancy import tenant_scope
from tests.api.test_team_default_agent import Stack, stack, start  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import ADMIN, TENANT, VIEWER

URL = "/v1/team-assistant/app-tools"
AID = ops_assistant_id("team_ops")
SALESFORCE = "mod_plugin_salesforce"


def op(name: str, access: str, module: str) -> OperationRef:
    return OperationRef(name, name, access, {"type": "object"}, False, module, module)


class Directory:
    async def operations(self) -> list[OperationRef]:
        return [
            op("salesforce_query", "read", SALESFORCE),
            op("salesforce_get_record", "read", SALESFORCE),
            op("salesforce_update_record", "write", SALESFORCE),
            op("github_list_issues", "read", "mod_plugin_github"),
        ]


async def give(c: Any, headers: dict[str, str]) -> Any:
    return await c.post(URL, json={"moduleIds": [SALESFORCE]}, headers=headers)


async def test_the_assistant_gets_the_apps_read_tools_once_and_nothing_else(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    rt.tool_directory = Directory()
    await start(c, ADMIN)
    r = await give(c, ADMIN)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert (data["state"], data["agentId"], data["tools"]) == (
        "given",
        AID,
        ["salesforce_get_record", "salesforce_query"],
    )
    live = rt.catalog.agent(AID)
    assert live is not None and {"salesforce_query", "salesforce_get_record"} <= set(live.tools), live
    assert not {"salesforce_update_record", "github_list_issues"} & set(live.tools), live.tools
    with tenant_scope(TENANT):
        before = (await registry(rt).row(AID))["version"]
    again = (await give(c, ADMIN)).json()["data"]
    with tenant_scope(TENANT):
        after = (await registry(rt).row(AID))["version"]
    assert again["state"] == "already" and before == after, again


async def test_someone_who_may_not_edit_agents_changes_nothing(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    rt.tool_directory = Directory()
    await start(c, ADMIN)
    r = await give(c, VIEWER)
    assert r.status_code == 403, r.text


async def test_a_draft_someone_is_editing_is_not_stepped_over(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    rt.tool_directory = Directory()
    await start(c, ADMIN)
    with tenant_scope(TENANT):
        reg = registry(rt)
        spec = dict((await reg.version(AID, int((await reg.row(AID))["published_version"])))["spec"])
        await reg.save(AID, {**spec, "role": "Our desk helper"}, by="jane@harborpine.example")
    data = (await give(c, ADMIN)).json()["data"]
    live = rt.catalog.agent(AID)
    assert data["state"] == "waiting" and live is not None and "salesforce_query" not in live.tools, data


def skill(tid: str, name: str, tools: list[str]) -> dict[str, Any]:
    return {
        "source": "plugin:opsai.salesforce",
        "kind": "skill",
        "id": tid,
        "version": 1,
        "title": name,
        "requires": {"tools": tools},
        "body": {"name": name, "useWhen": f"When {name.lower()} helps", "instructions": f"How to use {name}."},
    }


class Templates:
    """tools-service's plugin templates for the team: two skills the team can use and one naming a tool it lacks."""

    async def get(self, path: str, **_: Any) -> list[dict[str, Any]]:
        assert path == "/v1/plugin-templates"
        return [
            skill("salesforce-clients", "Salesforce clients", ["salesforce_query", "salesforce_get_record"]),
            skill(
                "salesforce-opportunities", "Salesforce opportunities", ["salesforce_query", "salesforce_update_record"]
            ),
            skill("salesforce-saving", "Salesforce saving", ["salesforce_save_records"]),
        ]


async def test_turning_an_app_on_pins_its_skills_with_the_tools_they_name_once(stack: Stack) -> None:  # noqa: F811
    # Routing comes from the app's own skills: an app turned on gave the assistant tools but no way to use them.
    c, rt = stack
    rt.tool_directory = Directory()
    rt.tool_reviews = SimpleNamespace(tools=Templates())  # type: ignore[assignment]
    await start(c, ADMIN)
    data = (await give(c, ADMIN)).json()["data"]
    assert sorted(data["skills"]) == ["Salesforce clients", "Salesforce opportunities"], data
    live = rt.catalog.agent(AID)
    assert live is not None
    assert sorted(s.name for s in live.skills) == ["Salesforce clients", "Salesforce opportunities"]
    # A skill's write tool comes with it, gated on every call; one naming a tool the team has not added is not pinned.
    assert "salesforce_update_record" in live.tools and "salesforce_save_records" not in live.tools
    again = (await give(c, ADMIN)).json()["data"]
    assert again["state"] == "already" and again["skills"] == [], again
