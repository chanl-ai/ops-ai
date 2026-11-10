"""GET /v1/tools, the Tools page's list (one row per tool), by failure mode: a tool shows no app, or the wrong one; an
app tool reads ready while its app is not connected for the person asking; the agents and workflows that use a tool
are missing; the facets count only the page, or name an app by its id alone; a filter or search is left to the
browser; and one tool cannot be read on its own."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ops_agents.activities.tool_directory import OperationRef

from .test_agent_limits import _app, _data  # pyright: ignore[reportPrivateUsage]


def op(name: str, module: str, server: str, access: str = "read", approval: bool = False) -> OperationRef:
    return OperationRef(
        name=name,
        description=f"{name} on {server}",
        access=access,
        input_schema={"type": "object"},
        requires_approval=approval,
        module_id=module,
        module_name=server,
    )


class Directory:
    """Two apps from plugins and a builder's own tool set."""

    async def operations(self) -> list[OperationRef]:
        return [
            op("crm_read_case", "mod_plugin_crm", "CRM"),
            op("crm_update_case", "mod_plugin_crm", "CRM", "write", approval=True),
            op("pay_refund", "mod_plugin_pay", "Payments", "write"),
            op("rates_read", "mod_rates", "Rates"),
        ]


class Apps:
    """tools-service's GET /v1/apps for the person asked for: CRM is connected; Payments is one each person signs
    in to, and this person has not."""

    def __init__(self) -> None:
        self.asked_for: list[str | None] = []

    async def cards(self, person: str | None, team: str | None) -> list[dict[str, Any]]:
        assert team, "the apps are read in the team the tools are listed for"
        self.asked_for.append(person)
        return [
            {"id": "plugin:crm", "name": "CRM", "kind": "plugin", "moduleIds": ["mod_plugin_crm"],
             "appState": "connected", "appGroup": "on", "signIn": "team"},
            {"id": "plugin:pay", "name": "Payments", "kind": "plugin", "moduleIds": ["mod_plugin_pay"],
             "appState": "needs_sign_in", "appGroup": "needs_you", "signIn": "person"},
        ]  # fmt: skip


async def granted(c: Any, tool: str) -> dict[str, Any]:
    made = _data(await c.post("/v1/agents", json={"name": "Case desk", "role": "Reads cases"}), 201)
    return _data(await c.patch(f"/v1/agents/{made['id']}", json={"toolIds": [tool]}))


async def test_each_tool_has_its_app_kind_status_and_users(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, app):
        apps = Apps()
        app.state.runtime.tool_directory, app.state.runtime.app_states = Directory(), apps
        agent = await granted(c, "crm_read_case")
        page = _data(await c.get("/v1/tools", params={"pageSize": 200}))
        rows = {r["id"]: r for r in page["data"]}
        crm = rows["crm_read_case"]
        assert (crm["app"], crm["kind"], crm["status"], crm["moduleId"]) == (
            {"id": "plugin:crm", "name": "CRM"}, "app", "ready", "mod_plugin_crm"
        ), crm  # fmt: skip
        assert crm["usedBy"] == {"agents": [{"id": agent["id"], "name": "Case desk"}], "workflows": []}, crm
        assert rows["crm_update_case"]["status"] == "needs_approval"
        assert rows["pay_refund"]["status"] == "needs_your_sign_in"
        assert (rows["rates_read"]["kind"], rows["rates_read"]["app"]) == (
            "custom", {"id": "module:mod_rates", "name": "Rates"}
        )  # fmt: skip
        assert apps.asked_for and all(p for p in apps.asked_for), "the person asking is the one the states are for"


async def test_paging_facets_filters_and_search_are_the_servers(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, app):
        app.state.runtime.tool_directory, app.state.runtime.app_states = Directory(), Apps()
        every = _data(await c.get("/v1/tools", params={"pageSize": 200}))
        first = _data(await c.get("/v1/tools", params={"pageSize": 2}))
        assert len(first["data"]) == 2 and first["pagination"]["total"] == len(every["data"]) > 2
        assert first["facets"]["kind"]["app"] == 3 and first["facets"]["kind"]["custom"] == 1, first["facets"]
        assert first["facets"]["app"]["plugin:crm"] == 2 and first["facets"]["status"]["needs_your_sign_in"] == 1
        # Every app the facet counts is named, the page's two rows' apps or not.
        assert first["appNames"] == {"plugin:crm": "CRM", "plugin:pay": "Payments", "module:mod_rates": "Rates"}
        only = _data(await c.get("/v1/tools", params={"kind": "custom", "pageSize": 200}))
        assert [r["id"] for r in only["data"]] == ["rates_read"]
        crm = _data(await c.get("/v1/tools", params={"app": "plugin:crm", "status": "ready", "pageSize": 200}))
        assert [r["id"] for r in crm["data"]] == ["crm_read_case"]
        found = _data(await c.get("/v1/tools", params={"search": "refund", "pageSize": 200}))
        assert [r["id"] for r in found["data"]] == ["pay_refund"]


async def test_one_tool_reads_as_its_row_does(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, app):
        app.state.runtime.tool_directory, app.state.runtime.app_states = Directory(), Apps()
        listed = {r["id"]: r for r in _data(await c.get("/v1/tools", params={"pageSize": 200}))["data"]}
        assert _data(await c.get("/v1/tools/crm_read_case")) == listed["crm_read_case"]
        assert (await c.get("/v1/tools/nope")).status_code == 404


class Kept(Directory):
    """A directory that keeps its list, as agents-service's does for 30 seconds, and counts each time it is dropped."""

    def __init__(self) -> None:
        self.dropped = 0

    def forget(self) -> None:
        self.dropped += 1


async def test_the_tools_list_reads_tools_fresh(tmp_path: Path) -> None:
    # A tool added to the team a moment ago must show on the Tools page and in the agent picker at once, not after the
    # kept list runs out.
    async with _app(tmp_path) as (c, app):
        kept = Kept()
        app.state.runtime.tool_directory, app.state.runtime.app_states = kept, Apps()
        _data(await c.get("/v1/tools", params={"pageSize": 200}))
        assert kept.dropped == 1, "the Tools page's list was read from the kept list"
