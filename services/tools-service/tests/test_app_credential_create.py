"""An admin adds the team's own app credential (POST /v1/app-credentials), by failure mode: the app keeps signing in
with Ops AI's app; the secret comes back in an answer; a second credential silently replaces the first; someone who
cannot manage the team's apps adds one; an app the team has not set up gets a half-made one; and a custom app is left
out. Rig: test_app_accounts."""

from __future__ import annotations

from .test_app_accounts import (
    ID,
    World,
    admin,
    world,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from .test_review_decisions import person

SAM = ("Sam Adeyemi", {"team_security": "admin"})
SECRET = "bank-own-client-secret-41c9"
APP = f"plugin:{ID}"


async def on_ops_ais_app(w: World, tenant: str) -> str:
    """Desk turned on with Ops AI's own app (the install's, test_plugin_credentials.INSTALL); its connection id."""
    on = await w.client.put(f"/v1/apps/plugin:{ID}/team", json={"enabled": True}, headers=admin(tenant))
    assert on.status_code == 200, on.text
    return str(on.json()["data"]["connectionId"])


def body(app: str = APP, **more: object) -> dict[str, object]:
    return {"app": app, "clientId": "bank-own-client", "clientSecret": SECRET, **more}


async def test_the_teams_own_client_replaces_ops_ais_app_and_its_secret_never_comes_back(
    world: World,  # noqa: F811
    tenant: str,
) -> None:
    conn = await on_ops_ais_app(world, tenant)
    made = await world.client.post("/v1/app-credentials", json=body(), headers=admin(tenant))
    assert made.status_code == 201, made.text
    row = made.json()["data"]
    assert (row["id"], row["app"], row["type"], row["permissions"]) == (conn, APP, "own", ["api"]), row
    listed = await world.client.get("/v1/app-credentials", headers=admin(tenant))
    detail = await world.client.get(f"/v1/apps/{APP}/accounts/{conn}", headers=admin(tenant))
    assert [c["type"] for c in listed.json()["data"] if c["app"] == APP] == ["own"]
    account = detail.json()["data"]
    assert account["settings"]["clientId"] == "bank-own-client", account
    assert all(SECRET not in r.text for r in (made, listed, detail))


async def test_a_second_credential_for_the_same_app_is_refused(world: World, tenant: str) -> None:  # noqa: F811
    await on_ops_ais_app(world, tenant)
    first = await world.client.post("/v1/app-credentials", json=body(), headers=admin(tenant))
    again = await world.client.post("/v1/app-credentials", json=body(clientId="other"), headers=admin(tenant))
    assert first.status_code == 201 and again.status_code == 409, again.text
    assert again.json()["error"]["code"] == "credential_exists", again.text


async def test_scopes_are_the_apps_own_and_its_required_ones_stay(world: World, tenant: str) -> None:  # noqa: F811
    await on_ops_ais_app(world, tenant)
    unknown = await world.client.post("/v1/app-credentials", json=body(scopes=["admin"]), headers=admin(tenant))
    assert unknown.status_code == 400, unknown.text
    made = await world.client.post("/v1/app-credentials", json=body(scopes=[]), headers=admin(tenant))
    assert made.status_code == 201 and made.json()["data"]["permissions"] == ["api"], made.text


async def test_a_builder_cannot_add_one(world: World, tenant: str) -> None:  # noqa: F811
    await on_ops_ais_app(world, tenant)
    builder = person(tenant, "James Richardson", {"team_platform": "builder"})
    r = await world.client.post("/v1/app-credentials", json=body(), headers=builder)
    assert r.status_code == 403, r.text


async def test_an_app_the_team_has_not_set_up_is_refused_and_nothing_is_made(world: World, tenant: str) -> None:  # noqa: F811
    r = await world.client.post("/v1/app-credentials", json=body(), headers=admin(tenant))
    assert r.status_code == 409 and r.json()["error"]["code"] == "app_not_set_up", r.text
    listed = await world.client.get("/v1/app-credentials", headers=admin(tenant))
    assert [c for c in listed.json()["data"] if c["app"] == APP] == []
    missing = await world.client.post("/v1/app-credentials", json=body(app="plugin:nope"), headers=admin(tenant))
    assert missing.status_code == 404, missing.text


async def test_a_custom_app_that_signs_in_takes_the_teams_client(world: World, tenant: str) -> None:  # noqa: F811
    settings = {
        "baseUrl": "https://crm.bank.test",
        "authorizeUrl": "https://login.bank.test/authorize",
        "tokenUrl": "https://login.bank.test/token",
        "clientId": "first",
    }
    made = await world.client.post(
        "/v1/apps", json={"name": "Bank CRM", "authKind": "oauth2_auth_code"}, headers=admin(tenant)
    )
    assert made.status_code == 201, made.text
    conn = made.json()["data"]
    saved = await world.client.patch(
        f"/v1/apps/{conn['id']}/accounts/{conn['id']}",
        json={"revision": conn["revision"], "settings": settings},
        headers=admin(tenant),
    )
    assert saved.status_code == 200, saved.text
    r = await world.client.post("/v1/app-credentials", json=body(app=conn["id"]), headers=admin(tenant))
    assert r.status_code == 201 and r.json()["data"]["type"] == "own", r.text
    shown = (await world.client.get(f"/v1/apps/{conn['id']}/accounts/{conn['id']}", headers=admin(tenant))).json()[
        "data"
    ]
    assert shown["settings"]["clientId"] == "bank-own-client" and SECRET not in str(shown), shown


async def test_replacing_the_secret_changes_the_teams_own_client_only(world: World, tenant: str) -> None:  # noqa: F811
    """Replace on the Credentials page reaches the team's own client, keeps its client id, and never Ops AI's app."""
    conn = await on_ops_ais_app(world, tenant)
    made = (await world.client.post("/v1/app-credentials", json=body(), headers=admin(tenant))).json()["data"]
    credential = made["credentialId"]
    assert credential, made
    builder = person(tenant, "James Richardson", {"team_platform": "builder"})
    url = f"/v1/app-credentials/{credential}/secret"
    assert (await world.client.put(url, json={"clientSecret": "x"}, headers=builder)).status_code == 403
    replaced = await world.client.put(url, json={"clientSecret": "bank-rotated-secret-2"}, headers=admin(tenant))
    assert replaced.status_code == 200 and "bank-rotated-secret-2" not in replaced.text, replaced.text
    fresh = await world.store.get(tenant, conn)
    assert fresh is not None
    assert fresh["settings"]["clientId"] == "bank-own-client" and fresh["credential_id"] == credential
    missing = await world.client.put(
        "/v1/app-credentials/cred_none/secret", json={"clientSecret": "x"}, headers=admin(tenant)
    )
    assert missing.status_code == 404, missing.text
