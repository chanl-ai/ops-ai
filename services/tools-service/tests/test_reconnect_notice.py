"""A team account that stops working, by failure mode: the call fails with the sign-in server's words
only, so a run's reason never says which app needs reconnecting or who does it; nobody is told until a run fails; the
same refusal tells admins again on every call; and an account whose sign-in ended with nothing to renew it reads as
never signed in. Rig and fake system: test_plugin_sign_in."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from ops_tools.store.connections import SHARED
from ops_tools.store.modules import service_outbox

from .test_plugin_sign_in import (
    CLIENT,
    CLIENT_SECRET,
    Rig,
    call_as_team,
    rig,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    turn_on,
)

NOTICE = "app_account.needs_reconnect"


async def notices(r: Rig, tenant: str) -> list[dict[str, Any]]:
    o = service_outbox.c
    async with r.store.engine.connect() as c:
        rows = (await c.execute(sa.select(service_outbox).where(o.tenant_id == tenant, o.name == NOTICE))).mappings()
        return [dict(row) for row in rows]


async def test_a_refused_team_account_names_the_app_to_reconnect_and_tells_admins_once(rig: Rig, tenant: str) -> None:  # noqa: F811
    on = await turn_on(rig, tenant, "test.client", client=(CLIENT, "not-the-secret"))
    connection_id = str(on.json()["data"]["connectionId"])
    refused = await call_as_team(rig, tenant, "test.client")
    error = refused.output["error"]
    assert "Client desk needs reconnecting" in error["message"], error
    assert "invalid_client" in error["message"] and "not-the-secret" not in str(refused.output)
    assert error["details"] == {
        "connectionId": connection_id,
        # The account's app, under which the console's Reconnect opens it.
        "appId": "plugin:test.client",
        "app": "Client desk",
        "account": "team",
        "state": "refused",
    }, error
    await call_as_team(rig, tenant, "test.client")
    told = await notices(rig, tenant)
    assert len(told) == 1, told
    assert told[0]["team_id"] == "team_platform"
    assert told[0]["payload"]["state"] == "refused" and told[0]["payload"]["app"] == "Client desk", told[0]
    assert "invalid_client" in told[0]["payload"]["reason"]


async def test_a_fixed_and_again_refused_account_tells_admins_again(rig: Rig, tenant: str) -> None:  # noqa: F811
    await turn_on(rig, tenant, "test.client", client=(CLIENT, "not-the-secret"))
    await call_as_team(rig, tenant, "test.client")
    await turn_on(rig, tenant, "test.client", client=(CLIENT, CLIENT_SECRET))
    assert (await call_as_team(rig, tenant, "test.client")).ok
    await turn_on(rig, tenant, "test.client", client=(CLIENT, "wrong-again"))
    # The held token is turned down, so the gateway asks for a new one with the wrong secret.
    rig.system.expire()
    await call_as_team(rig, tenant, "test.client")
    assert len(await notices(rig, tenant)) == 2


async def test_an_ended_team_sign_in_reads_expired_not_never_signed_in(rig: Rig, tenant: str) -> None:  # noqa: F811
    on = await turn_on(rig, tenant, "test.person", signIn="team", client=("person-app", "person-app-secret"))
    assert on.status_code == 200, on.text
    connection_id = str(on.json()["data"]["connectionId"])
    # A sign-in that gave no refresh token, whose token ended a minute ago.
    await rig.auth.tokens.store_answer(tenant, connection_id, {"access_token": "at-ended", "expires_in": -60}, SHARED)
    failed = await call_as_team(rig, tenant, "test.person")
    error = failed.output["error"]
    assert "Person desk needs reconnecting" in error["message"], error
    today = datetime.now(UTC)
    assert f"ended on {today.day} {today:%b %Y}" in error["message"], error
    assert error["details"]["state"] == "expired", error
    await call_as_team(rig, tenant, "test.person")
    told = await notices(rig, tenant)
    assert [t["payload"]["state"] for t in told] == ["expired"], told


async def test_a_team_account_never_signed_in_is_not_reported_as_needing_a_reconnect(rig: Rig, tenant: str) -> None:  # noqa: F811
    await turn_on(rig, tenant, "test.person", signIn="team", client=("person-app", "person-app-secret"))
    failed = await call_as_team(rig, tenant, "test.person")
    assert failed.output["error"]["code"] == "NOT_SIGNED_IN", failed.output
    assert "reconnecting" not in failed.output["error"]["message"]
    assert await notices(rig, tenant) == []
