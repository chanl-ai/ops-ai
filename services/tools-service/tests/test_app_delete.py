"""Deleting a custom app, by failure mode: a tool still pointing at one of its accounts would fail on its next call, so
the delete is refused naming each tool (with its id, for a link) and the accounts it would take; a delete that left a
second account or its secret behind would keep a credential nobody can see; a plugin's app is turned off, never
deleted here; and someone who may not manage the team's apps deletes nothing."""

from __future__ import annotations

from typing import Any

import httpx

from .test_connections import TEAM, admin, client  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_review_decisions import person


async def _made(c: httpx.AsyncClient, who: dict[str, str]) -> dict[str, Any]:
    res = await c.post("/v1/apps", json={"name": "Core banking API", "authKind": "api_key"}, headers=who)
    assert res.status_code == 201, res.text
    return res.json()["data"]


def _at(account: dict[str, Any]) -> str:
    return f"/v1/apps/{account['appId']}/accounts/{account['id']}"


def _module(connection_id: str) -> dict[str, Any]:
    return {
        "name": "ledger",
        "displayName": "Ledger",
        "system": "Ledger",
        "type": "http",
        "endpoint": "",
        "connectionId": connection_id,
        "http": {
            "name": "ledger_read",
            "description": "d",
            "access": "read",
            "method": "GET",
            "url": "https://ledger.test/a",
        },
    }


async def _second(c: httpx.AsyncClient, who: dict[str, str], app: str) -> dict[str, Any]:
    made = await c.post(
        f"/v1/apps/{app}/accounts",
        json={"name": "Second", "credentials": {"baseUrl": "https://ledger.test", "key": "k-2"}},
        headers=who,
    )
    assert made.status_code == 201, made.text
    return made.json()["data"]


async def test_an_app_a_tool_uses_is_not_deleted_and_the_tools_and_accounts_are_named(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    who = admin(tenant)
    security = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    assert (await client.post("/v1/egress/hosts", json={"value": "ledger.test"}, headers=security)).status_code == 201
    first = await _made(client, who)
    app = str(first["appId"])
    second = await _second(client, who, app)
    builder = person(tenant, "James Richardson", {TEAM: "builder"})
    tool = await client.post("/v1/tool-modules", json=_module(str(second["id"])), headers=builder)
    assert tool.status_code == 201, tool.text

    refused = await client.delete(f"/v1/apps/{app}", headers=who)
    error = refused.json()["error"]
    assert refused.status_code == 409 and error["code"] == "app_in_use", refused.text
    assert [t["name"] for t in error["details"]["tools"]] == ["Ledger"], error
    assert error["details"]["tools"][0]["id"] == tool.json()["data"]["id"], error
    assert sorted(error["details"]["accounts"]) == sorted([first["name"], "Second"]), error
    assert "Ledger" in error["message"], error
    # Nothing was taken: both accounts still answer.
    for account in (first, second):
        assert (await client.get(_at(account), headers=who)).status_code == 200


async def test_deleting_an_app_takes_every_account_and_its_secrets(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    who = admin(tenant)
    first = await _made(client, who)
    app = str(first["appId"])
    await client.patch(_at(first), json={"revision": first["revision"], "secrets": {"key": "k-1"}}, headers=who)
    second = await _second(client, who, app)

    gone = await client.delete(f"/v1/apps/{app}", headers=who)
    assert gone.status_code == 200, gone.text
    assert sorted(gone.json()["data"]["accounts"]) == sorted([first["name"], "Second"]), gone.text
    for account in (first, second):
        assert (await client.get(_at(account), headers=who)).status_code == 404
    left = (await client.get("/v1/secrets", headers=person(tenant, "Sam Adeyemi", {TEAM: "admin"}))).json()["data"]
    assert not [s for s in left if s.get("connectionId") in (first["id"], second["id"])], left
    assert app not in [c["id"] for c in (await client.get("/v1/apps", headers=who)).json()["data"]]


async def test_only_someone_who_manages_the_teams_apps_deletes_one(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    first = await _made(client, admin(tenant))
    viewer = person(tenant, "Ravi Menon", {TEAM: "viewer"})
    refused = await client.delete(f"/v1/apps/{first['appId']}", headers=viewer)
    assert refused.status_code == 403, refused.text
    assert (await client.get(_at(first), headers=admin(tenant))).status_code == 200


async def test_changing_an_apps_sign_in_kind_names_every_account_and_drops_what_it_held(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    # A key kept after the app signs in another way would still be sent, or sit unseen; so it goes, and each account
    # is named as needing its new sign-in.
    who = admin(tenant)
    first = await _made(client, who)
    app = str(first["appId"])
    await client.patch(
        _at(first),
        json={
            "revision": first["revision"],
            "settings": {"baseUrl": "https://ledger.test"},
            "secretValues": {"key": "k-1"},
        },
        headers=who,
    )
    second = await _second(client, who, app)
    changed = await client.patch(f"/v1/apps/{app}", json={"kind": "basic"}, headers=who)
    assert changed.status_code == 200, changed.text
    assert sorted(changed.json()["data"]["accounts"]) == sorted([first["name"], "Second"]), changed.text
    for account in (first, second):
        detail = (await client.get(_at(account), headers=who)).json()["data"]
        assert detail["authKind"] == "basic" and detail["status"] == "needs_reconnect", detail
        held = [k for k, part in detail["secrets"].items() if part["set"]]
        assert detail["settings"].get("baseUrl") == "https://ledger.test" and not held, detail
    left = (await client.get("/v1/secrets", headers=who)).json()["data"]
    assert not [s for s in left if s.get("connectionId") in (first["id"], second["id"])], left
