"""An account's partial writes, by failure mode: a sign-in that saves the instance it read rewrites the account's
settings and drops the name of the team's own client secret, so the next sign-in sends no secret and the system
refuses it."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import isolation
from ops_tools.store.connections import ConnectionStore

TEAM = "team_platform"


async def test_a_write_of_settings_alone_keeps_the_teams_client_and_its_secret(
    engine: AsyncEngine, tenant: str
) -> None:
    store, now = ConnectionStore(engine), datetime.now(UTC)
    row = {
        "tenant_id": tenant, "id": "ca_desk", "app_id": "plugin:desk", "team_id": TEAM, "name": "Desk",
        "auth_kind": "oauth2_auth_code", "status": "healthy", "revision": 1, "created_by": "t", "created_at": now,
        "updated_by": "t", "updated_at": now,
        "settings": {"baseUrl": "https://login.desk.test", "clientId": "team-app"},
        "secrets": {"clientSecret": "CONN_CA_DESK_CLIENT_SECRET"},
    }  # fmt: skip
    with isolation.scope(tenant, TEAM):
        assert await store.create(row, actor="t", at=now)
        held = await store.get(tenant, "ca_desk")
        assert held is not None
        # As a finished sign-in saves the instance its token named: the settings, nothing about secrets.
        signed = {**held["settings"], "baseUrl": "https://acme.my.desk.test"}
        await store.change(tenant, "ca_desk", 1, {"settings": signed}, actor="t", at=now)
        after = await store.get(tenant, "ca_desk")
    assert after is not None
    assert after["settings"]["baseUrl"] == "https://acme.my.desk.test"
    assert after["settings"]["clientId"] == "team-app", after["settings"]
    assert after["secrets"] == {"clientSecret": "CONN_CA_DESK_CLIENT_SECRET"}, after["secrets"]
