"""The first admin on an install where nothing seeds: signs in with the bootstrap password into the Security team as
admin, and a later run (each release calls it) changes nothing the admin may since have changed."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
import pytest
import sqlalchemy as sa
from pydantic import SecretStr

from ops_access.policies import PUBLISH_AREAS, publish_mode
from ops_platform.api.app import create_public_app
from ops_platform.bootstrap import FirstAdmin, bootstrap
from ops_platform.keys import dev_signer
from ops_platform.store.identity import IdentityStore
from ops_platform.store.seeding import write_seed
from ops_platform.store.tables import audit_entries, policies
from ops_platform.store.tenancy import TenantDb
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


async def policy_value(client: httpx.AsyncClient, headers: dict[str, str], key: str) -> object:
    r = await client.get(f"/v1/policies/{key}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]["value"]


async def admin_headers(client: httpx.AsyncClient, admin: FirstAdmin) -> dict[str, str]:
    r = await sign_in(client, admin, PASSWORD)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": admin.team_id}


async def test_a_new_workspace_publishes_without_review_and_calls_any_public_address(
    production: httpx.AsyncClient, database_url: str
) -> None:
    admin = first_admin()
    await bootstrap(database_url, admin, iterations=1000)
    headers = await admin_headers(production, admin)
    value = await policy_value(production, headers, "publishReview")
    assert isinstance(value, dict)
    reviews = cast(dict[str, Any], value)
    # The first team and a team added later read the same: every area publishes at once.
    for team in (admin.team_id, "team_added_later"):
        assert {a: publish_mode(reviews, team, a) for a in PUBLISH_AREAS} == dict.fromkeys(PUBLISH_AREAS, "never")
    assert await policy_value(production, headers, "egressNewHosts") == "any_public"
    # Writes run without asking, a maker's ask-first included; step-up is off by the catalogue's own default.
    changes = await policy_value(production, headers, "appChanges")
    assert isinstance(changes, dict) and changes["*"]["makersAsk"] is False and changes["*"]["ask"] is False
    assert await policy_value(production, headers, "stepUp") is False


async def test_a_new_workspace_stores_its_makers_ask_through_a_save_with_an_audit_entry(database_url: str) -> None:
    admin = first_admin()
    await bootstrap(database_url, admin, iterations=1000)
    async with TenantDb.open(database_url).tenant_tx(admin.tenant_id) as c:
        rows = await c.execute(
            sa.select(audit_entries.c.actor, audit_entries.c.detail).where(
                audit_entries.c.action == "policy.set", audit_entries.c.target_id == "appChanges"
            )
        )
        saved = [(r.actor, r.detail["after"]["makersAsk"]) for r in rows]
    assert saved == [("workspace", False)], saved


async def rerun(database_url: str, admin: FirstAdmin) -> None:
    """What every release and dev restart runs on a workspace that already exists."""
    assert await bootstrap(database_url, admin, iterations=1000) == "unchanged"
    await write_seed(
        TenantDb.open(database_url),
        {"tenant": {"id": admin.tenant_id, "name": "x", "allowedDomains": []}, "teams": [], "people": []},
        security_team=admin.team_id,
    )


async def test_a_workspace_that_stores_no_makers_ask_gets_none_written_by_a_later_run(database_url: str) -> None:
    """An older workspace stays unset, so tools-service refuses its writes with the fix instead of loosening them."""
    admin = first_admin()
    await bootstrap(database_url, admin, iterations=1000)
    db = TenantDb.open(database_url)
    async with db.tenant_tx(admin.tenant_id) as c:
        # As a workspace made before new ones stored makers' asks: its team saved the switch, nothing else.
        older = {admin.team_id: {"ask": False, "answer": "person"}}
        await c.execute(policies.update().where(policies.c.key == "appChanges").values(value=older))
    await rerun(database_url, admin)
    async with db.tenant_tx(admin.tenant_id) as c:
        held = (await c.execute(sa.select(policies.c.value).where(policies.c.key == "appChanges"))).scalar_one()
    assert held == older, held


async def test_a_later_run_keeps_what_an_admin_turned_back_on(production: httpx.AsyncClient, database_url: str) -> None:
    admin = first_admin()
    await bootstrap(database_url, admin, iterations=1000)
    headers = await admin_headers(production, admin)
    put = await production.put("/v1/policies/egressNewHosts", json={"value": "ask_security"}, headers=headers)
    assert put.status_code == 200, put.text
    asks = {"ask": True, "answer": "person", "reviewerRole": None, "testAccountsNeverAsk": True, "testRunsAsk": True}
    put = await production.put("/v1/policies/appChanges", json={"value": {**asks, "makersAsk": True}}, headers=headers)
    assert put.status_code == 200, put.text
    changes = await policy_value(production, headers, "appChanges")
    # A boot and a seed run on a workspace that already exists write no setting.
    await rerun(database_url, admin)
    assert await policy_value(production, headers, "egressNewHosts") == "ask_security"
    assert await policy_value(production, headers, "appChanges") == changes
