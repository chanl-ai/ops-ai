"""An admin adds the team's own app credential (POST /v1/app-credentials) with no account, and accounts pick it, by
failure mode: making one needs an account set up first; the secret comes back in an answer or is listed as a value
tools reference; a turn-on still takes a typed client; someone who cannot manage the team's apps adds one; deleting an
account takes the team's credential with it; an account picks another app's credential; and Replace reaches Ops AI's
app. Rig: test_app_accounts."""

from __future__ import annotations

from ops_tools.store.secrets import SecretStore

from .test_app_accounts import (
    ID,
    World,
    admin,
    world,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from .test_review_decisions import person

SECRET = "bank-own-client-secret-41c9"
APP = f"plugin:{ID}"


def body(**more: object) -> dict[str, object]:
    return {"app": APP, "clientId": "bank-own-client", "clientSecret": SECRET, **more}


async def made(w: World, tenant: str, **more: object) -> dict[str, object]:
    r = await w.client.post("/v1/app-credentials", json=body(**more), headers=admin(tenant))
    assert r.status_code == 201, r.text
    return dict(r.json()["data"])


async def turned_on(w: World, tenant: str, **more: object) -> str:
    on = await w.client.put(f"/v1/apps/{APP}/team", json={"enabled": True, **more}, headers=admin(tenant))
    assert on.status_code == 200, on.text
    return str(on.json()["data"]["connectionId"])


async def account(w: World, tenant: str, conn: str) -> dict[str, object]:
    r = await w.client.get(f"/v1/apps/{APP}/accounts/{conn}", headers=admin(tenant))
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


async def test_a_credential_needs_no_account_and_its_secret_is_not_a_value_tools_reference(
    world: World,  # noqa: F811
    tenant: str,
) -> None:
    row = await made(world, tenant)
    assert (row["app"], row["type"], row["clientId"], row["permissions"], row["accounts"]) == (
        APP, "own", "bank-own-client", [{"id": "api", "label": "Read and change records", "required": True}], 0,
    ), row  # fmt: skip
    listed = await world.client.get("/v1/app-credentials", params={"app": APP}, headers=admin(tenant))
    assert [c["id"] for c in listed.json()["data"] if c["type"] == "own"] == [row["id"]], listed.text
    cred = await world.store.credential(tenant, str(row["id"]))
    assert cred is not None and cred["secret_name"], cred
    secrets = SecretStore(world.store.engine)
    shown = await secrets.page(tenant, str(cred["team_id"]), "", offset=0, limit=100)
    held = [s for s in await secrets.listed(tenant, str(cred["team_id"])) if s["name"] == cred["secret_name"]]
    assert held and held[0]["credential_id"] == row["id"] and held[0]["connection_id"] is None, held
    assert cred["secret_name"] not in [s["name"] for s in shown]
    assert SECRET not in str(row) + listed.text


async def test_a_turn_on_picks_the_credential_and_takes_no_typed_client(world: World, tenant: str) -> None:  # noqa: F811
    row = await made(world, tenant)
    typed = await world.client.put(
        f"/v1/apps/{APP}/team", json={"enabled": True, "clientId": "x", "clientSecret": "y"}, headers=admin(tenant)
    )
    assert typed.status_code == 400 and "clientId" in typed.text, typed.text
    inside = await world.client.put(
        f"/v1/apps/{APP}/team", json={"enabled": True, "credentials": {"clientId": "x"}}, headers=admin(tenant)
    )
    assert inside.status_code == 400 and inside.json()["error"]["code"] == "client_in_credentials", inside.text
    conn = await turned_on(world, tenant, credentialId=row["id"])
    shown = await account(world, tenant, conn)
    assert (shown["credentialId"], shown["platformApp"]) == (row["id"], None), shown
    assert dict(shown["settings"])["clientId"] == "bank-own-client" and SECRET not in str(shown), shown  # pyright: ignore[reportArgumentType, reportCallIssue]


async def test_a_second_credential_for_the_same_app_is_its_own(world: World, tenant: str) -> None:  # noqa: F811
    first = await made(world, tenant)
    second = await made(world, tenant, clientId="other", name="Desk sandbox app")
    listed = await world.client.get("/v1/app-credentials", params={"app": APP}, headers=admin(tenant))
    own = {c["id"]: c["clientId"] for c in listed.json()["data"] if c["type"] == "own"}
    assert own == {first["id"]: "bank-own-client", second["id"]: "other"}, own


async def test_scopes_are_the_apps_own_and_its_required_ones_stay(world: World, tenant: str) -> None:  # noqa: F811
    unknown = await world.client.post("/v1/app-credentials", json=body(scopes=["admin"]), headers=admin(tenant))
    assert unknown.status_code == 400, unknown.text
    row = await made(world, tenant, scopes=[])
    assert row["permissions"] == [{"id": "api", "label": "Read and change records", "required": True}], row


async def test_a_builder_cannot_add_one_and_an_unknown_app_has_none(world: World, tenant: str) -> None:  # noqa: F811
    builder = person(tenant, "James Richardson", {"team_platform": "builder"})
    r = await world.client.post("/v1/app-credentials", json=body(), headers=builder)
    assert r.status_code == 403, r.text
    missing = await world.client.post("/v1/app-credentials", json=body(app="plugin:nope"), headers=admin(tenant))
    assert missing.status_code == 404, missing.text


async def test_deleting_an_account_leaves_the_credential_for_the_next(world: World, tenant: str) -> None:  # noqa: F811
    row = await made(world, tenant)
    conn = await turned_on(world, tenant, credentialId=row["id"])
    sandbox = await world.client.post(
        f"/v1/apps/{APP}/accounts", json={"name": "Desk sandbox", "sandbox": True, "credentialId": row["id"]},
        headers=admin(tenant),
    )  # fmt: skip
    assert sandbox.status_code == 201, sandbox.text
    page = await world.client.get(f"/v1/app-credentials/{row['id']}", headers=admin(tenant))
    assert sorted(a["id"] for a in page.json()["data"]["accountsList"]) == sorted([conn, sandbox.json()["data"]["id"]])
    gone = await world.client.delete(f"/v1/apps/{APP}/accounts/{sandbox.json()['data']['id']}", headers=admin(tenant))
    assert gone.status_code == 204, gone.text
    cred = await world.store.credential(tenant, str(row["id"]))
    assert cred is not None, "deleting an account deleted the team's credential"
    held = [s["name"] for s in await SecretStore(world.store.engine).listed(tenant, str(cred["team_id"]))]
    assert cred["secret_name"] in held, "deleting an account deleted the credential's client secret"
    left = await world.client.get(f"/v1/app-credentials/{row['id']}", headers=admin(tenant))
    assert [a["id"] for a in left.json()["data"]["accountsList"]] == [conn], left.text
    assert (await world.client.get("/v1/app-credentials/cred_none", headers=admin(tenant))).status_code == 404


async def test_an_account_moves_onto_a_credential_of_its_own_app_only(world: World, tenant: str) -> None:  # noqa: F811
    conn = await turned_on(world, tenant)
    before = await account(world, tenant, conn)
    assert before["platformApp"] == ID, before
    row = await made(world, tenant)
    moved = await world.client.patch(
        f"/v1/apps/{APP}/accounts/{conn}",
        json={"revision": before["revision"], "credentialId": row["id"]},
        headers=admin(tenant),
    )
    assert moved.status_code == 200, moved.text
    after = moved.json()["data"]
    assert (after["credentialId"], after["platformApp"]) == (row["id"], None), after
    custom = await world.client.post(
        "/v1/apps", json={"name": "Bank CRM", "authKind": "oauth2_auth_code"}, headers=admin(tenant)
    )
    other = await made(world, tenant, app=custom.json()["data"]["id"])
    wrong = await world.client.patch(
        f"/v1/apps/{APP}/accounts/{conn}",
        json={"revision": after["revision"], "credentialId": other["id"]},
        headers=admin(tenant),
    )
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "credential_other_app", wrong.text


async def test_replacing_the_secret_changes_the_teams_own_client_only(world: World, tenant: str) -> None:  # noqa: F811
    """Replace on the Credentials page reaches the team's own client and keeps its accounts on it."""
    row = await made(world, tenant)
    conn = await turned_on(world, tenant, credentialId=row["id"])
    builder = person(tenant, "James Richardson", {"team_platform": "builder"})
    url = f"/v1/app-credentials/{row['id']}/secret"
    assert (await world.client.put(url, json={"clientSecret": "x"}, headers=builder)).status_code == 403
    replaced = await world.client.put(url, json={"clientSecret": "bank-rotated-secret-2"}, headers=admin(tenant))
    assert replaced.status_code == 200 and "bank-rotated-secret-2" not in replaced.text, replaced.text
    fresh = await world.store.get(tenant, conn)
    assert fresh is not None
    assert fresh["settings"]["clientId"] == "bank-own-client" and fresh["credential_id"] == row["id"]
    ops_ai = await world.client.put(
        f"/v1/app-credentials/ops-ai:{APP}/secret", json={"clientSecret": "x"}, headers=admin(tenant)
    )
    assert ops_ai.status_code == 404, ops_ai.text
