"""GET /v1/agents/{agent_id}/tool-apps and its /{app_id}/tools, the agent page's tools grouped by app, by failure
mode: an app not found by the words of one of its tools; an app's counts and granted marks disagreeing with what the
agent holds; another team's agent answering; a row repeated or skipped from page to page; the picker failing when
tools-service cannot be reached; a caller without the tools or the agents view right reading either list; another
team's agent offered as a tool; an app's state or its not-added count left for the console to work out; a search's
listed tools cut before they are ordered; an app whose id holds a slash not opening. An unknown app answering is
checked by use case uc-agents-1."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.activities.tool_directory import OperationRef, ToolsUnavailable
from tests.engine.test_lifecycle_rights import (  # noqa: F401  # a fixture
    BUILDER,
    person,
    stack,  # pyright: ignore[reportUnusedImport]
)

from ..saves import save_agent
from .test_agent_limits import FRAUD, _app, _data  # pyright: ignore[reportPrivateUsage]

SALESFORCE, GITHUB = "plugin:opsai.salesforce", "plugin:opsai.github"
LENDER = person("lena", "team_lending", "builder")


def op(name: str, title: str, description: str, module: tuple[str, str], access: str = "read") -> OperationRef:
    return OperationRef(
        name=name,
        description=description,
        access=access,
        input_schema={"type": "object"},
        requires_approval=access != "read",
        module_id=module[0],
        module_name=module[1],
        title=title,
    )


SF, GH, DESK = ("mod_sf", "Salesforce"), ("mod_gh", "GitHub"), ("mod_desk", "Ticket desk")
OPERATIONS = [
    op("salesforce_find_cases", "Find cases", "Search support cases by subject", SF),
    op("salesforce_get_record", "Get record", "Read one record by its id", SF),
    op("salesforce_update_case", "Update case", "Change a case's status", SF, "write"),
    op("github_list_reviews", "List reviews", "Pull requests waiting for a reviewer", GH),
    op("github_get_issue", "Get issue", "Read one issue", GH),
    op("desk_get_ticket", "Get ticket", "Read one ticket", DESK),
]


class Directory:
    """tools-service's grantable operations: the ones the team has added."""

    def __init__(self, operations: list[OperationRef], *, down: bool = False) -> None:
        self.listed, self.down = operations, down

    async def operations(self) -> list[OperationRef]:
        if self.down:
            raise ToolsUnavailable("down")
        return self.listed


class Cards:
    """tools-service's app cards: Salesforce connected with 3 of its 15 tools added, GitHub turned on but waiting for
    an admin to connect it. The ticket desk's module has no card."""

    def __init__(self, *, down: bool = False, more: list[dict[str, Any]] | None = None) -> None:
        self.down, self.more = down, more or []

    async def cards(self, person: str | None, team: str | None) -> list[dict[str, Any]]:
        if self.down:
            raise ToolsUnavailable("down")
        return [
            *self.more,
            {
                "id": GITHUB, "kind": "plugin", "name": "GitHub", "appState": "off", "appGroup": "needs_admin",
                "signIn": "person", "toolsCount": 2, "toolsAdded": 2, "moduleIds": ["mod_gh"],
            },
            {
                "id": SALESFORCE, "kind": "plugin", "name": "Salesforce", "appState": "connected", "appGroup": "on",
                "signIn": "team", "toolsCount": 15, "toolsAdded": 3, "moduleIds": ["mod_sf"],
            },
        ]  # fmt: skip


async def test_an_app_is_found_by_the_words_of_one_of_its_tools(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, app):
        app.state.runtime.tool_directory, app.state.runtime.app_states = Directory(OPERATIONS), Cards()
        found = _data(await c.get(f"/v1/agents/{FRAUD}/tool-apps", params={"search": "pull requests"}))["data"]
        assert [a["id"] for a in found] == [GITHUB], "the app whose tool matches, and no other"
        assert found[0]["matches"] == [
            {"id": "github_list_reviews", "label": "List reviews", "access": "read", "granted": False}
        ]
        every = _data(await c.get(f"/v1/agents/{FRAUD}/tool-apps", params={"limit": 100}))["data"]
        assert all(a["matches"] == [] for a in every), "no search, no matching tools listed"


async def test_counts_and_granted_marks_are_the_agents_own_grants(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, app):
        app.state.runtime.tool_directory, app.state.runtime.app_states = Directory(OPERATIONS), Cards()
        agent = _data(await c.post("/v1/agents", json={"name": "Case desk", "role": "Works cases"}), 201)["id"]
        held = ["salesforce_find_cases", "salesforce_update_case", "github_get_issue"]
        assert (await save_agent(c, agent, {"toolIds": held})).status_code == 200

        apps = _data(await c.get(f"/v1/agents/{agent}/tool-apps", params={"limit": 100}))["data"]
        by_id = {a["id"]: a for a in apps}
        counts = {k: by_id[SALESFORCE][k] for k in ("toolsTotal", "toolsOffered", "toolsGranted")}
        assert counts == {"toolsTotal": 15, "toolsOffered": 3, "toolsGranted": 2}
        assert by_id[GITHUB]["toolsGranted"] == 1
        assert (by_id[SALESFORCE]["connected"], by_id[GITHUB]["connected"]) == (True, False)
        ids = [a["id"] for a in apps]
        assert ids.index(SALESFORCE) < ids.index(GITHUB), "connected apps first, then by name"
        granted = _data(await c.get(f"/v1/agents/{agent}/tool-apps", params={"granted": "true", "limit": 100}))
        assert sorted(a["id"] for a in granted["data"]) == [GITHUB, SALESFORCE], "only apps the agent holds a tool of"
        other = _data(await c.get(f"/v1/agents/{FRAUD}/tool-apps", params={"limit": 100}))["data"]
        assert next(a for a in other if a["id"] == SALESFORCE)["toolsGranted"] == 0, "another agent's grants"

        tools = _data(await c.get(f"/v1/agents/{agent}/tool-apps/{SALESFORCE}/tools"))["data"]
        assert {t["id"]: t["granted"] for t in tools} == {
            "salesforce_find_cases": True,
            "salesforce_get_record": False,
            "salesforce_update_case": True,
        }
        assert {t["label"]: t["requiresApproval"] for t in tools}["Update case"] is True
        left = _data(await c.get(f"/v1/agents/{agent}/tool-apps/{SALESFORCE}/tools", params={"granted": "false"}))
        assert [t["id"] for t in left["data"]] == ["salesforce_get_record"]


async def test_another_teams_agent_answers_not_found(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    c, _ = stack
    made = await c.post("/v1/agents", json={"name": "Loan desk", "role": "Reads loans"}, headers=LENDER)
    assert made.status_code == 201, made.text
    theirs = made.json()["data"]["id"]
    # The fixture keeps the teams apart: the agent itself is missing for the other team.
    assert (await c.get(f"/v1/agents/{theirs}", headers=BUILDER)).status_code == 404

    own = await c.get(f"/v1/agents/{theirs}/tool-apps", headers=LENDER)
    assert own.status_code == 200, own.text
    app_id = own.json()["data"]["data"][0]["id"]
    assert (await c.get(f"/v1/agents/{theirs}/tool-apps/{app_id}/tools", headers=LENDER)).status_code == 200
    for path in (f"/v1/agents/{theirs}/tool-apps", f"/v1/agents/{theirs}/tool-apps/{app_id}/tools"):
        refused = await c.get(path, headers=BUILDER)
        assert refused.status_code == 404 and refused.json()["error"]["code"] == "not_found", refused.text


async def every_page(c: AsyncClient, path: str, limit: int) -> list[str]:
    """The ids of each page in turn, following `nextCursor` to the end."""
    ids: list[str] = []
    cursor: str | None = None
    for _ in range(20):
        params = {"limit": limit} | ({"cursor": cursor} if cursor else {})
        page = _data(await c.get(path, params=params))
        assert len(page["data"]) <= limit
        ids += [row["id"] for row in page["data"]]
        cursor = page["nextCursor"]
        if cursor is None:
            return ids
    raise AssertionError(f"{path} never ended: {len(ids)} rows in 20 pages")


async def test_paging_shows_each_app_and_each_tool_once(tmp_path: Path) -> None:
    modules = [op(f"read_{i:02d}", f"Read {i}", "Reads", (f"mod_{i:02d}", f"System {i:02d}")) for i in range(30)]
    wide = [op(f"wide_{i:02d}", f"Wide {i}", "Reads", ("mod_wide", "Wide system")) for i in range(30)]
    async with _app(tmp_path) as (c, app):
        app.state.runtime.tool_directory = Directory(modules + wide)
        apps = await every_page(c, f"/v1/agents/{FRAUD}/tool-apps", 7)
        assert len(apps) == len(set(apps)), "an app on two pages"
        whole = _data(await c.get(f"/v1/agents/{FRAUD}/tool-apps", params={"limit": 100}))["data"]
        assert apps == [a["id"] for a in whole] and len(apps) >= 31, "the pages are the one list, in its order"

        wide_app = next(a["id"] for a in whole if a["name"] == "Wide system")
        tools = await every_page(c, f"/v1/agents/{FRAUD}/tool-apps/{wide_app}/tools", 7)
        assert sorted(tools) == [f"wide_{i:02d}" for i in range(30)], "each tool once, none skipped"


async def test_the_apps_this_service_knows_are_listed_while_tools_service_is_down(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, app):
        app.state.runtime.tool_directory, app.state.runtime.app_states = Directory(OPERATIONS), Cards(down=True)
        no_cards = await c.get(f"/v1/agents/{FRAUD}/tool-apps", params={"limit": 100})
        assert no_cards.status_code == 200, no_cards.text
        by_name = {a["name"]: a for a in no_cards.json()["data"]["data"]}
        assert by_name["Salesforce"]["toolsOffered"] == 3, "its tools stay grantable, grouped by their module's name"

        app.state.runtime.tool_directory = Directory(OPERATIONS, down=True)
        down = await c.get(f"/v1/agents/{FRAUD}/tool-apps", params={"limit": 100})
        assert down.status_code == 200, down.text
        names = {a["name"] for a in down.json()["data"]["data"]}
        assert "Agents" in names and "Salesforce" not in names, "the team's own agents, and no app it cannot read"


NO_TOOLS_VIEW = person("tia", "team_ops", "builder", unticked=(("tools", "view"),))
NO_AGENTS_VIEW = person("abe", "team_ops", "builder", unticked=(("agents", "view"),))


@pytest.mark.parametrize("without", [NO_TOOLS_VIEW, NO_AGENTS_VIEW], ids=["tools view", "agents view"])
async def test_both_lists_are_refused_without_the_view_right(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
    without: dict[str, str],
) -> None:
    c, _ = stack
    made = await c.post("/v1/agents", json={"name": "Case desk", "role": "Works cases"}, headers=BUILDER)
    assert made.status_code == 201, made.text
    apps = f"/v1/agents/{made.json()['data']['id']}/tool-apps"
    listed = await c.get(apps, headers=BUILDER)
    assert listed.status_code == 200, listed.text
    tools = f"{apps}/{quote(listed.json()['data']['data'][0]['id'], safe='')}/tools"
    assert (await c.get(tools, headers=BUILDER)).status_code == 200
    for path in (apps, tools):
        refused = await c.get(path, headers=without)
        assert refused.status_code == 403, f"{path}: {refused.status_code} {refused.text}"


async def test_another_teams_agent_is_not_offered_as_a_tool(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    c, _ = stack
    lender = person("lars", "team_lending", "admin")
    theirs = (await c.post("/v1/agents", json={"name": "Loan desk", "role": "Reads loans"}, headers=lender)).json()
    tool = f"agent:{theirs['data']['id']}"
    published = await c.post(
        f"/v1/agents/{theirs['data']['id']}/publish-requests",
        json={"version": theirs["data"]["version"], "note": "first"},
        headers=lender,
    )
    assert published.status_code == 201, published.text
    # Live, so its own team is offered it: the refusal below is about the team, not an agent nobody is offered.
    own = await c.get("/v1/tools/options", params={"search": "Loan desk"}, headers=lender)
    assert tool in [o["id"] for o in own.json()["data"]["data"]], own.text

    mine = (await c.post("/v1/agents", json={"name": "Case desk", "role": "Works cases"}, headers=BUILDER)).json()
    flat = await c.get("/v1/tools/options", params={"search": "Loan desk"}, headers=BUILDER)
    assert tool not in [o["id"] for o in flat.json()["data"]["data"]], "the flat picker offers another team's agent"
    apps = f"/v1/agents/{mine['data']['id']}/tool-apps"
    found = (await c.get(apps, params={"search": "Loan desk"}, headers=BUILDER)).json()["data"]["data"]
    assert tool not in [m["id"] for a in found for m in a["matches"]], "the search names another team's agent"
    grouped = (await c.get(f"{apps}/agents/tools", params={"limit": 100}, headers=BUILDER)).json()
    assert tool not in [t["id"] for t in grouped["data"]["data"]], "the Agents group lists another team's agent"


async def test_each_app_says_its_state_and_how_many_tools_are_not_added(tmp_path: Path) -> None:
    # A card whose count trails the tools the team holds: tools-service counts its catalog, the team added one more.
    desk = {
        "id": "con_desk", "kind": "custom", "name": "Ticket desk", "appState": "needs_sign_in",
        "appGroup": "needs_you", "signIn": "person", "toolsCount": 0, "toolsAdded": None, "moduleIds": ["mod_desk"],
    }  # fmt: skip
    async with _app(tmp_path) as (c, app):
        app.state.runtime.tool_directory, app.state.runtime.app_states = Directory(OPERATIONS), Cards(more=[desk])
        apps = _data(await c.get(f"/v1/agents/{FRAUD}/tool-apps", params={"limit": 100}))["data"]
        by_id = {a["id"]: a for a in apps}
        states = {k: by_id[k]["appState"] for k in (SALESFORCE, GITHUB, "con_desk")}
        assert states == {SALESFORCE: "connected", GITHUB: "off", "con_desk": "needs_sign_in"}, "the card's own state"
        assert by_id["agents"]["appState"] is None, "a group with no card has no state to draw"
        not_added = {k: by_id[k]["notAdded"] for k in (SALESFORCE, GITHUB, "con_desk", "agents")}
        assert not_added == {SALESFORCE: 12, GITHUB: 0, "con_desk": 0, "agents": 0}, "total less offered, never below 0"


async def test_a_searchs_listed_tools_are_the_first_five_by_label(tmp_path: Path) -> None:
    labels = ["Golf", "Bravo", "Echo", "Alpha", "Foxtrot", "Delta", "Charlie"]
    zulu = [op(f"zulu_{i}", label, "A zulu report", ("mod_zulu", "Zulu")) for i, label in enumerate(labels)]
    async with _app(tmp_path) as (c, app):
        app.state.runtime.tool_directory = Directory(zulu)
        found = _data(await c.get(f"/v1/agents/{FRAUD}/tool-apps", params={"search": "zulu report"}))["data"]
        assert [m["label"] for m in found[0]["matches"]] == ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]


async def test_an_app_whose_id_holds_a_slash_opens_by_its_encoded_id(tmp_path: Path) -> None:
    # A tool with no module groups under its server's name, which a person may have typed with a slash.
    billing = OperationRef(
        name="read_invoice",
        description="Reads one invoice",
        access="read",
        input_schema={"type": "object"},
        requires_approval=False,
        module_id=None,
        module_name="Billing/Invoices",
    )
    async with _app(tmp_path) as (c, app):
        app.state.runtime.tool_directory = Directory([billing])
        apps = _data(await c.get(f"/v1/agents/{FRAUD}/tool-apps", params={"search": "Billing/Invoices"}))["data"]
        app_id = next(a["id"] for a in apps if a["name"] == "Billing/Invoices")
        assert "/" in app_id, "the fixture's app id holds the slash"
        tools = await c.get(f"/v1/agents/{FRAUD}/tool-apps/{quote(app_id, safe='')}/tools")
        assert tools.status_code == 200, tools.text
        assert [t["id"] for t in tools.json()["data"]["data"]] == ["read_invoice"]
