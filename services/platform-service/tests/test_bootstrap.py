"""The first admin on an install where nothing seeds: signs in with the bootstrap password into the Security team as
admin, and a later run (each release calls it) changes nothing the admin may since have changed."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from ops_platform.api.app import create_public_app
from ops_platform.bootstrap import FirstAdmin, bootstrap
from ops_platform.keys import dev_signer
from ops_platform.store.identity import IdentityStore
from ops_service_kit.ids import new_id
from ops_service_kit.settings import Settings

PASSWORD = "first-admin-password-1"


def first_admin(password: str = PASSWORD) -> FirstAdmin:
    tenant = new_id("ten")
    return FirstAdmin(
        tenant_id=tenant,
        tenant_name="Staging bank",
        team_id=f"team_sec_{tenant}",
        team_name="Security",
        email=f"{tenant}@bank.test",
        name="First Admin",
        password=password,
    )


@pytest.fixture
async def production(database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    """platform-service as it runs outside dev: no demo password, so only a stored password signs anyone in."""
    store = IdentityStore.open(database_url)
    app = create_public_app(store, dev_signer(), demo_password=None, audiences=["platform"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://platform") as client:
        yield client
    await store.close()


async def sign_in(client: httpx.AsyncClient, admin: FirstAdmin, password: str) -> httpx.Response:
    return await client.post("/v1/auth/sign-in", json={"email": admin.email, "password": password})


async def test_the_first_admin_signs_in_with_the_bootstrap_password_as_security_admin(
    production: httpx.AsyncClient, database_url: str
) -> None:
    admin = first_admin()
    assert await bootstrap(database_url, admin, iterations=1000) == "created"
    r = await sign_in(production, admin, PASSWORD)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["principal"]["roles"] == {admin.team_id: "admin"}
    # Only a workspace admin reads the workspace's teams; the team is its security and default team.
    headers = {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": admin.team_id}
    teams = await production.get("/v1/settings/workspace-teams", headers=headers)
    assert teams.status_code == 200, teams.text
    assert teams.json()["data"] == {"securityTeam": admin.team_id, "defaultTeam": admin.team_id}


async def test_a_second_run_keeps_the_first_password(production: httpx.AsyncClient, database_url: str) -> None:
    admin = first_admin()
    await bootstrap(database_url, admin, iterations=1000)
    again = FirstAdmin(**{**admin.__dict__, "password": "a-different-password-2", "team_name": "Renamed"})
    assert await bootstrap(database_url, again, iterations=1000) == "unchanged"
    assert (await sign_in(production, admin, PASSWORD)).status_code == 200
    assert (await sign_in(production, admin, "a-different-password-2")).status_code == 401


def test_missing_values_and_a_short_password_are_refused_before_anything_is_written() -> None:
    with pytest.raises(ValueError, match=r"set OPS_BOOTSTRAP_TENANT_ID, .*OPS_BOOTSTRAP_ADMIN_PASSWORD"):
        FirstAdmin.from_settings(Settings())
    short = Settings(
        bootstrap_tenant_id="local",
        bootstrap_tenant_name="Bank",
        bootstrap_team_name="Security",
        bootstrap_admin_email="a@bank.test",
        bootstrap_admin_name="A",
        bootstrap_admin_password=SecretStr("short"),
    )
    with pytest.raises(ValueError, match="at least 12 characters"):
        FirstAdmin.from_settings(short)
