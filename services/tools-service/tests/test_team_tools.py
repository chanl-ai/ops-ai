"""Which of an app's tools a team adds from the app's catalog, by failure mode: a new app leaves a tool off, so a
developer who connects it cannot write until someone finds the catalog; a tool not added still runs when called by
name or is offered to agents; an app turned on before the catalog existed loses tools its agents hold; a person who
may not manage the team's apps adds or removes a tool; the app's catalog does not say which tools are added; and the
app's card does not count them, so the agent picker cannot say how many wait in the catalog."""

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
    return {t["name"]: t["added"] for t in page["tools"]}


async def test_a_new_app_starts_with_every_tool_on_its_writes_included(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    # Writes are on from the start; "Ask before changes" is what keeps a person in the loop, not a missing tool.
    (c, _, _, _), _ = desk_rig
    on = await _on(c, tenant)
    every = ("fields_search", "fields_find", "fields_echo", "fields_post_message", "fields_transfer")
    assert on == dict.fromkeys(every, True), on


async def test_someone_who_manages_the_teams_apps_adds_and_removes_tools_and_a_viewer_cannot(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    (c, _, _, _), _ = desk_rig
    await _on(c, tenant)
    viewer = person(tenant, "Ravi Menon", {TEAM: "viewer"})
    body = {"tools": ["fields_post_message", "fields_transfer"]}
    refused = await c.post(f"/v1/apps/{APP}/tools", json=body, headers=viewer)
    assert refused.status_code == 403, refused.text
    added = await c.post(f"/v1/apps/{APP}/tools", json=body, headers=admin(tenant))
    assert added.status_code == 200 and [t["added"] for t in added.json()["data"]] == [True, True], added.text
    page = (await c.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]
    assert all(t["added"] for t in page["tools"]), page["tools"]
    assert (await c.delete(f"/v1/apps/{APP}/tools/fields_search", headers=viewer)).status_code == 403
    removed = await c.delete(f"/v1/apps/{APP}/tools/fields_search", headers=admin(tenant))
    assert removed.status_code == 200 and removed.json()["data"]["added"] is False, removed.text


async def test_a_tool_not_added_is_refused_at_the_gateway_in_one_plain_sentence(rig: Rig) -> None:  # noqa: F811
    await rig.bindings.set_tools(rig.tenant, TEAM, ID, ["search"])
    assert (await rig.call("search")).ok
    out = await rig.call("post_message", {"channel": "C1", "text": "hi"})
    assert not out.ok and out.output["error"]["code"] == "TOOL_NOT_ADDED", out
    said = out.output["error"]["message"]
    assert "Post a message" in said and "Tools tab" in said and "fields_" not in said, said
    assert rig.seen and all(not r.url.path.endswith("/messages") for r in rig.seen)


async def test_an_app_turned_on_before_the_catalog_keeps_every_tool_added(rig: Rig) -> None:  # noqa: F811
    # The rig's binding was made the way every team's was before the catalog: no list of added tools.
    assert (await rig.call("post_message", {"channel": "C1", "text": "hi"})).ok
    assert (await rig.call("search")).ok


async def test_agents_are_not_offered_tools_the_team_has_not_added(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    # The grantable operations agents-service lists, grants and hands a run leave out what this answers.
    (c, host, _, _), _ = desk_rig
    await _on(c, tenant)
    assert await host.tools_off(tenant, TEAM) == set()
    await c.delete(f"/v1/apps/{APP}/tools/fields_transfer", headers=admin(tenant))
    assert await host.tools_off(tenant, TEAM) == {"fields_transfer"}
    assert await host.tools_off(tenant, "team_other") == set()


async def test_the_apps_card_counts_the_tools_added_of_its_catalog(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    (c, _, _, _), _ = desk_rig
    await _on(c, tenant)
    card = next(x for x in (await c.get("/v1/apps", headers=admin(tenant))).json()["data"] if x["id"] == APP)
    assert (card["toolsCount"], card["toolsAdded"]) == (5, 5), card
    await c.delete(f"/v1/apps/{APP}/tools/fields_transfer", headers=admin(tenant))
    card = next(x for x in (await c.get("/v1/apps", headers=admin(tenant))).json()["data"] if x["id"] == APP)
    assert card["toolsAdded"] == 4, card


async def test_an_auth_configs_permissions_follow_the_added_tools(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    # A permission no added tool needs is not asked for; adding a tool asks for its permission at the next
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

    # A new app has every tool on, so its write permission is asked from the start; removing the write drops it.
    assert "records:write" in await asked()
    removed = await c.delete(f"/v1/apps/{sites}/tools/fields_sites_update_record", headers=admin(tenant))
    assert removed.status_code == 200, removed.text
    assert "records:write" not in await asked()

    async def listed() -> list[str]:
        page = (await c.get(f"/v1/apps/{sites}", headers=admin(tenant))).json()["data"]
        return [p["id"] for cfg in page["authConfigs"] for p in cfg["permissions"]]

    assert "openid" in await listed() and "records:write" not in await listed()
    added = await c.post(
        f"/v1/apps/{sites}/tools", json={"tools": ["fields_sites_update_record"]}, headers=admin(tenant)
    )
    assert added.status_code == 200 and added.json()["data"][0]["askedAtSignIn"] is True, added.text
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
