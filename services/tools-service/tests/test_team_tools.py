"""Which of an app's tools a team lets its agents and workflows use, by failure mode: a new app hands every write
tool to agents before anyone chose it; a switched-off tool still runs when called by name; an app turned on before
the switch existed loses tools its agents hold; a person who may not manage the team's apps switches a tool; and the
app page does not say which tools are on."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from .test_plugin_manifest_fields import (  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixtures
    ID,
    TEAM,
    Rig,
    TokenDesk,
    admin,
    desk_rig,  # pyright: ignore[reportUnusedImport]
    rig,  # pyright: ignore[reportUnusedImport]
    turn_on,
)
from .test_review_decisions import person

APP = f"plugin:{ID}"


async def _on(c: httpx.AsyncClient, tenant: str) -> dict[str, bool]:
    turned = await c.put(
        f"/v1/apps/{APP}/team", json={"enabled": True, "credentials": {"token": "tok-1"}}, headers=admin(tenant)
    )
    assert turned.status_code == 200, turned.text
    page = (await c.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]
    return {t["name"]: t["on"] for t in page["tools"]}


async def test_a_new_app_starts_with_its_read_tools_on_and_its_write_tools_off(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    (c, _, _, _), _ = desk_rig
    on = await _on(c, tenant)
    assert {k for k, v in on.items() if v} == {"fields_search", "fields_find", "fields_echo"}, on
    assert {k for k, v in on.items() if not v} == {"fields_post_message", "fields_transfer"}, on


async def test_someone_who_manages_the_teams_apps_switches_a_tool_and_a_viewer_cannot(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    (c, _, _, _), _ = desk_rig
    await _on(c, tenant)
    viewer = person(tenant, "Ravi Menon", {TEAM: "viewer"})
    refused = await c.put(f"/v1/apps/{APP}/tools/fields_post_message", json={"on": True}, headers=viewer)
    assert refused.status_code == 403, refused.text
    turned = await c.put(f"/v1/apps/{APP}/tools/fields_post_message", json={"on": True}, headers=admin(tenant))
    assert turned.status_code == 200 and turned.json()["data"]["on"] is True, turned.text
    page = (await c.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]
    assert {t["name"]: t["on"] for t in page["tools"]}["fields_post_message"] is True
    off = await c.put(f"/v1/apps/{APP}/tools/fields_search", json={"on": False}, headers=admin(tenant))
    assert off.status_code == 200 and off.json()["data"]["on"] is False, off.text


async def test_a_switched_off_tool_is_refused_at_the_gateway_in_one_plain_sentence(rig: Rig) -> None:  # noqa: F811
    await rig.bindings.set_tools(rig.tenant, TEAM, ID, ["search"])
    assert (await rig.call("search")).ok
    out = await rig.call("post_message", {"channel": "C1", "text": "hi"})
    assert not out.ok and out.output["error"]["code"] == "TOOL_OFF", out
    said = out.output["error"]["message"]
    assert "Post a message" in said and "Tools tab" in said and "fields_" not in said, said
    assert rig.seen and all(not r.url.path.endswith("/messages") for r in rig.seen)


async def test_an_app_turned_on_before_the_switch_keeps_every_tool_on(rig: Rig) -> None:  # noqa: F811
    # The rig's binding was made the way every team's was before the switch: no list of tools.
    assert (await rig.call("post_message", {"channel": "C1", "text": "hi"})).ok
    assert (await rig.call("search")).ok


async def test_agents_are_not_offered_the_tools_the_team_switched_off(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    # The grantable operations agents-service lists, grants and hands a run leave out what this answers.
    (c, host, _, _), _ = desk_rig
    await _on(c, tenant)
    assert await host.tools_off(tenant, TEAM) == {"fields_post_message", "fields_transfer"}
    await c.put(f"/v1/apps/{APP}/tools/fields_transfer", json={"on": True}, headers=admin(tenant))
    assert await host.tools_off(tenant, TEAM) == {"fields_post_message"}
    assert await host.tools_off(tenant, "team_other") == set()


async def test_an_auth_configs_permissions_follow_the_switched_on_tools(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    # A permission no switched-on tool needs is not asked for; switching a tool on asks for its permission at the next
    # sign-in, and the tool says so until the team account has it.
    (c, _, _, _), _ = desk_rig
    sites = "plugin:test.fields-sites"
    on = await turn_on(c, tenant, "test.fields-sites", client=("multi-app", "app-secret"))
    account = str(on.json()["data"]["connectionId"])

    async def asked() -> list[str]:
        started = await c.post(
            f"/v1/apps/{sites}/accounts/{account}/sign-in", json={"account": "team"}, headers=admin(tenant)
        )
        assert started.status_code == 200, started.text
        return parse_qs(urlsplit(str(started.json()["data"]["authorizeUrl"])).query)["scope"][0].split()

    assert "records:write" not in await asked()

    async def listed() -> list[str]:
        page = (await c.get(f"/v1/apps/{sites}", headers=admin(tenant))).json()["data"]
        return [p["id"] for cfg in page["authConfigs"] for p in cfg["permissions"]]

    assert "openid" in await listed() and "records:write" not in await listed()
    turned = await c.put(f"/v1/apps/{sites}/tools/fields_sites_update_record", json={"on": True}, headers=admin(tenant))
    assert turned.status_code == 200 and turned.json()["data"]["askedAtSignIn"] is True, turned.text
    assert "records:write" in await asked()
    assert "records:write" in await listed()


async def test_deleting_a_plugins_app_turns_it_off_and_takes_its_accounts(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    # The plugin stays installed for other teams; this team's accounts and their secrets go, and the app reads off.
    (c, _, store, _), _ = desk_rig
    on = await c.put(
        f"/v1/apps/{APP}/team", json={"enabled": True, "credentials": {"token": "tok-1"}}, headers=admin(tenant)
    )
    account = str(on.json()["data"]["connectionId"])
    gone = await c.delete(f"/v1/apps/{APP}", headers=admin(tenant))
    assert gone.status_code == 200 and gone.json()["data"]["accounts"], gone.text
    assert await store.get(tenant, account) is None
    card = next(a for a in (await c.get("/v1/apps", headers=admin(tenant))).json()["data"] if a["id"] == APP)
    assert not card.get("connectionId") and card["appState"] != "connected", card
