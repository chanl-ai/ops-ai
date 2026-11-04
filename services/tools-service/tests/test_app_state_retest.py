"""A team account whose test failed reads as working again once a test passes: a card left on test_failed after the
system came back would keep telling the team to reconnect an account that works. Rig and fake system:
test_plugin_sign_in."""

from __future__ import annotations

from .test_plugin_sign_in import (
    CLIENT,
    CLIENT_SECRET,
    Rig,
    account_url,
    admin,
    call_as_team,
    rig,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    turn_on,
)


async def app_state(r: Rig, tenant: str) -> str:
    cards = (await r.client.get("/v1/apps", headers=admin(tenant))).json()["data"]
    return str(next(c for c in cards if c["id"] == "plugin:test.client")["appState"])


async def test_a_passing_test_after_a_failed_one_reads_connected(rig: Rig, tenant: str) -> None:  # noqa: F811
    on = await turn_on(rig, tenant, "test.client", clientId=CLIENT, clientSecret=CLIENT_SECRET)
    connection_id = str(on.json()["data"]["connectionId"])
    assert (await call_as_team(rig, tenant, "test.client")).ok
    url = f"{await account_url(rig, tenant, connection_id)}/test"
    rig.system.down = True
    failed = await rig.client.post(url, json={"account": "team"}, headers=admin(tenant))
    assert failed.json()["data"]["health"]["status"] == "failed", failed.text
    assert await app_state(rig, tenant) == "test_failed"
    rig.system.down = False
    passed = await rig.client.post(url, json={"account": "team"}, headers=admin(tenant))
    assert passed.json()["data"]["health"]["status"] == "ok", passed.text
    assert await app_state(rig, tenant) == "connected"
