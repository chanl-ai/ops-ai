"""Who uses an app before a team turns it off (`GET /v1/apps/{app_id}/used-by`), by failure mode: the
answer names another app's tools or misses one of this app's; it lists people outside the team's agents and
workflows; a viewer reads it; and a missing agents-service answer reads as "nobody uses it"."""

from __future__ import annotations

from ops_service_kit.errors import ServiceUnavailable
from ops_tools.modules.tool_users import StaticToolUsers

from .test_app_accounts import TEAM, World, admin, connected, world  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_plugins import ID
from .test_review_decisions import person

URL = f"/v1/apps/plugin:{ID}/used-by"


async def test_the_apps_users_are_its_tools_agents_and_workflows(world: World, tenant: str) -> None:  # noqa: F811
    await connected(world, tenant)
    assert isinstance(world.users, StaticToolUsers)
    world.users.uses = {
        "desk_get_case": [
            {"kind": "agent", "id": "agt_1", "name": "Records helper"},
            {"kind": "workflow", "id": "wf_1", "name": "Case intake"},
        ],
        "other_app_tool": [{"kind": "agent", "id": "agt_2", "name": "Not this app"}],
    }
    r = await world.client.get(URL, headers=admin(tenant))
    assert r.status_code == 200, r.text
    assert r.json()["data"] == {
        "agents": [{"id": "agt_1", "name": "Records helper", "tools": ["desk_get_case"]}],
        "workflows": [{"id": "wf_1", "name": "Case intake", "tools": ["desk_get_case"]}],
    }


async def test_a_viewer_may_not_read_who_uses_an_app(world: World, tenant: str) -> None:  # noqa: F811
    await connected(world, tenant)
    r = await world.client.get(URL, headers=person(tenant, "Ravi Menon", {TEAM: "viewer"}))
    assert r.status_code == 403, r.text


async def test_no_answer_from_agents_service_is_not_nobody(world: World, tenant: str) -> None:  # noqa: F811
    await connected(world, tenant)

    async def down(*_: object) -> dict[str, list[dict[str, str]]]:
        raise ServiceUnavailable("agents-service is down", code="tool_users_unavailable")

    world.users.of = down  # type: ignore[method-assign]
    r = await world.client.get(URL, headers=admin(tenant))
    assert r.status_code == 503, r.text


async def test_the_app_pages_tools_carry_who_uses_each_and_a_missing_answer_is_not_nobody(
    world: World,  # noqa: F811
    tenant: str,
) -> None:
    """The app page's Tools tab: each tool's agents and workflows, joined in the answer; agents-service down leaves
    Used by unknown instead of empty, and the page still answers."""
    await connected(world, tenant)
    assert isinstance(world.users, StaticToolUsers)
    world.users.uses = {"desk_get_case": [{"kind": "agent", "id": "agt_1", "name": "Records helper"}]}
    page = await world.client.get(f"/v1/apps/plugin:{ID}", headers=admin(tenant))
    assert page.status_code == 200, page.text
    tools = {t["name"]: t for t in page.json()["data"]["tools"]}
    assert tools["desk_get_case"]["usedBy"] == {"agents": [{"id": "agt_1", "name": "Records helper"}], "workflows": []}

    async def down(*_: object) -> dict[str, list[dict[str, str]]]:
        raise ServiceUnavailable("agents-service is down", code="tool_users_unavailable")

    world.users.of = down  # type: ignore[method-assign]
    again = await world.client.get(f"/v1/apps/plugin:{ID}", headers=admin(tenant))
    assert again.status_code == 200, again.text
    assert all(t.get("usedBy") is None for t in again.json()["data"]["tools"])
