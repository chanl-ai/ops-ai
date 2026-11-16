"""Every GET route of platform-service in its statement budget (`budgets.toml`, data-access standard DA1 and DA6), by
failure mode: a list whose statements grow with its rows, a route over its row, and a route that opens more
transactions or checks out more connections than its row lists. Each list the routes read grows by `n` people,
invites, keys, teams, custom roles and a person's grants of them, break-glass rows, the admin's connected assistants,
sign-in secrets and providers per seeding; the internal app's one GET is held by
the same file."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ops_identity import mint_service_token
from ops_platform.store.roles import mirror_membership
from ops_platform.store.tables import (
    api_keys,
    members,
    role_assignments,
    roles,
    sessions,
    signin_break_glass,
    teams,
    users,
)
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.logging import captured_logging
from ops_service_kit.testing import Seeded, SeedTeam, StatementBudget, budget_check, over_budget

from .conftest import CALLER, MCP_URL, Platform, SignInRig
from .test_mcp_oauth import REGISTRATION

BUDGETS = Path(__file__).parents[1] / "budgets.toml"

statement_budget = pytest.fixture(budget_check)


@pytest.fixture
def app(signin: SignInRig) -> FastAPI:
    return signin.app


@pytest.fixture
def client(signin: SignInRig) -> httpx.AsyncClient:
    return signin.public


@pytest.fixture
def seed_team(signin: SignInRig) -> SeedTeam:
    """`n` more people in the Security team (the rig admin's acting team), invites, API keys, teams, custom roles,
    sign-in secrets and OIDC providers; once, a SAML provider and a test sign-in through it for the ids their paths
    name."""
    ids: dict[str, str] = {"team_id": signin.ops_team, "role_id": "viewer", "key": "requesterMayDecide"}

    async def seed(n: int) -> Seeded:
        now = now_iso()
        if "client_id" not in ids:
            # An assistant registered once, for the consent page's query and the connections the admin holds.
            made = await signin.public.post("/oauth/register", json=REGISTRATION)
            assert made.status_code == 201, made.text
            ids["client_id"] = made.json()["client_id"]
            ids["resource"] = f"{MCP_URL}/mcp/{signin.ops_team}"
            me = await signin.public.get("/v1/me", headers=signin.admin)
            ids["admin_id"] = me.json()["data"]["user"]["id"]
        async with signin.engine.begin() as c:
            for _ in range(n):
                user, team, role = new_id("usr"), new_id("team"), new_id("role")
                email = f"{user}@{signin.zone}"
                await c.execute(
                    users.insert().values(
                        id=user, tenant_id=signin.tenant, email=email, name=user, status="active", created_at=now
                    )
                )
                await c.execute(
                    members.insert().values(
                        id=new_id("mem"), tenant_id=signin.tenant, team_id=signin.security_team, user_id=user,
                        email=email, role="viewer", status="active", created_at=now, updated_at=now,
                    )
                )  # fmt: skip
                await mirror_membership(
                    c, tenant_id=signin.tenant, team_id=signin.security_team, user_id=user, member_role="viewer",
                    security_team=signin.security_team, granted_by="test", at=now,
                )  # fmt: skip
                ids.setdefault("person_id", user)
                # A break-glass row, a connected assistant of the admin's and a custom role given to the person.
                await c.execute(
                    signin_break_glass.insert().values(
                        tenant_id=signin.tenant, user_id=user, added_by="test", added_at=now
                    )
                )  # fmt: skip
                await c.execute(
                    sessions.insert().values(
                        id=new_id("ses"), tenant_id=signin.tenant, user_id=ids["admin_id"], auth_method="password",
                        refresh_hash=new_id("rh"), expires_at="2999-01-01T00:00:00.000Z", created_at=now,
                        last_seen_at=now, kind="mcp", client_id=ids["client_id"], team_id=signin.ops_team,
                        resource=ids["resource"], code_used_at=now,
                    )
                )  # fmt: skip
                await c.execute(
                    teams.insert().values(
                        id=team, tenant_id=signin.tenant, name=f"T {team}", owner_groups=[], scope="owned",
                        created_at=now,
                    )
                )  # fmt: skip
                await c.execute(
                    roles.insert().values(
                        tenant_id=signin.tenant, id=role, name=f"R {role}", builtin=False, description="",
                        created_at=now,
                    )
                )  # fmt: skip
                await c.execute(
                    role_assignments.insert().values(
                        id=new_id("ras"), tenant_id=signin.tenant, subject_kind="person", subject_id=ids["person_id"],
                        role_id=role, team_id=signin.security_team, granted_by="test", reason="test", source="grant",
                        created_at=now,
                    )
                )  # fmt: skip
                key = new_id("key")
                await c.execute(
                    api_keys.insert().values(
                        id=key, tenant_id=signin.tenant, team_id=signin.security_team, name="ci", prefix=key,
                        secret_hash="0" * 64, scopes=["read"], created_by=user, created_at=now,
                    )
                )  # fmt: skip
        emails = [f"{new_id('inv')}@{signin.zone}" for _ in range(n)]
        invited = await signin.public.post(
            "/v1/settings/members/invite", headers=signin.admin, json={"emails": emails, "role": "viewer"}
        )
        assert invited.status_code == 200, invited.text
        ids.setdefault("token", invited.json()["data"]["invites"][0]["token"])
        for i in range(n):
            put = await signin.public.put(
                f"/v1/settings/sign-in/secrets/BANK_{n}_{i}", json={"value": "s3cret"}, headers=signin.admin
            )
            assert put.status_code == 200, put.text
            await signin.oidc(f"o{n}x{i}.{signin.zone}")
        if "sp_id" not in ids:
            provider = await signin.saml(f"saml.{signin.zone}")
            listed = (await signin.public.get("/v1/settings/sign-in/providers", headers=signin.admin)).json()["data"]
            # The metadata path names the provider's service-provider id, the last part of its consumer URL.
            ids["sp_id"] = next(p for p in listed if p["id"] == provider)["saml"]["acsUrl"].rsplit("/", 1)[1]
            tried = await signin.public.post(f"/v1/settings/sign-in/providers/{provider}/test", headers=signin.admin)
            assert tried.status_code == 200, tried.text
            ids["flow_id"] = str(tried.json()["data"]["flowId"])
        return Seeded(headers=signin.admin, ids=dict(ids))

    return seed


async def test_every_get_stays_in_its_budget(statement_budget: StatementBudget) -> None:
    problems = await statement_budget(BUDGETS)
    assert problems == [], "\n".join(problems)


async def test_the_internal_get_stays_in_its_budget(platform: Platform) -> None:
    app, client = platform.internal_app, platform.internal

    tenant = (await platform.person()).tenant_id
    token = mint_service_token(CALLER, service="agents", audience="platform", tenant_id=tenant, ttl_s=60)

    async def seed(_n: int) -> Seeded:
        return Seeded(headers={"Authorization": f"Bearer {token}"})

    with captured_logging("statement-budget") as stream:
        problems = await over_budget(app, client, seed, BUDGETS, stream)
    assert problems == [], "\n".join(problems)
