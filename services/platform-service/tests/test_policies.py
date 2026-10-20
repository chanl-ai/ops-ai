"""Workspace access policies at rest (c-186), by failure mode: a policy that starts closed, a change with no audit
entry, a change that leaves tokens on the old permission version, a value the policy does not take stored, and one
tenant's setting reaching another."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_access import POLICIES
from ops_access.policies import BY_KEY, KINDS
from ops_identity import dev_service_signer, mint_service_token
from ops_platform.store.policies import PolicyStore
from ops_platform.store.roles import RoleStore
from ops_platform.store.tables import audit_entries, tenants
from ops_platform.store.tenancy import TenantDb
from ops_service_kit.ids import new_id, now_iso

from .conftest import DEMO_PASSWORD, SignInRig

DEFAULTS: dict[str, Any] = {
    "requesterMayDecide": True,
    "extractionFloor": 0.8,
    "stepUp": False,
    "publishReview": {},
    "chatThreadsOwnerOnly": True,
    "securityTeamAddsSecrets": False,
    "memoryRetentionDays": None,
    "reviewSlaHours": 8,
    "toolWritesNeedApproval": {},
    # No team set: off for every team until one turns it on (owner, 2026-10-18; c-298, c-302, c-300, c-295).
    "aiSteps": {},
    "taskAssist": {},
    "checkBeforeSend": {},
    "pageImages": {},
    # Per team and on unless a team turns it off (c-321): {} names no team, so every team masks.
    "aiStepsMaskPersonalData": {},
}
# The AI uses: the one documented exception to open defaults, off until a team turns them on.
OFF_UNTIL_ON = ("aiSteps", "taskAssist", "checkBeforeSend", "pageImages")
ADA = "ada@northfieldbank.com"


async def tenant(engine: AsyncEngine) -> str:
    t = new_id("ten")
    async with engine.begin() as c:
        await c.execute(
            tenants.insert().values(id=t, name=t, status="active", allowed_domains=[], created_at=now_iso())
        )
    return t


async def audit(engine: AsyncEngine, t: str) -> list[tuple[str, str, dict[str, object]]]:
    async with engine.begin() as c:
        rows = await c.execute(
            sa.select(audit_entries.c.action, audit_entries.c.target_id, audit_entries.c.detail)
            .where(audit_entries.c.tenant_id == t)
            .order_by(audit_entries.c.at, audit_entries.c.id)
        )
    return [(r.action, r.target_id, r.detail) for r in rows]


async def test_a_new_workspace_has_every_policy_open_but_the_ai_uses_which_start_off(engine: AsyncEngine) -> None:
    assert {p.key: p.default for p in POLICIES} == DEFAULTS
    assert await PolicyStore(TenantDb(engine)).values(await tenant(engine)) == DEFAULTS
    # Per team, and no team named: no team has them until it turns them on.
    assert all(BY_KEY[k].per_team and DEFAULTS[k] == {} for k in OFF_UNTIL_ON)


async def test_a_change_is_audited_with_before_and_after_and_moves_the_permission_version(engine: AsyncEngine) -> None:
    db, t = TenantDb(engine), await tenant(engine)
    store, version = PolicyStore(db), await RoleStore(db).version(t)
    assert await store.set(t, "requesterMayDecide", False, by=ADA, request_id="r1") == (True, False)
    assert await store.set(t, "extractionFloor", 0.9, by=ADA, request_id="r2") == (0.8, 0.9)
    assert await store.set(t, "extractionFloor", None, by=ADA, request_id="r3") == (0.9, None)
    assert await store.values(t) == {**DEFAULTS, "requesterMayDecide": False, "extractionFloor": None}
    assert await RoleStore(db).version(t) == version + 3
    assert await audit(engine, t) == [
        ("policy.set", "requesterMayDecide", {"before": True, "after": False}),
        ("policy.set", "extractionFloor", {"before": 0.8, "after": 0.9}),
        ("policy.set", "extractionFloor", {"before": 0.9, "after": None}),
    ]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("stepUp", "yes"),
        ("extractionFloor", 1.5),
        ("extractionFloor", True),
        ("memoryRetentionDays", 0),
        ("memoryRetentionDays", 1.5),
        ("reviewSlaHours", 0),
        ("reviewSlaHours", None),
        ("noSuchPolicy", True),
    ],
)
async def test_a_value_the_policy_does_not_take_is_refused_and_nothing_written(
    engine: AsyncEngine, key: str, value: object
) -> None:
    db, t = TenantDb(engine), await tenant(engine)
    with pytest.raises(ValueError, match=key):
        await PolicyStore(db).set(t, key, value, by=ADA, request_id="r1")
    assert await PolicyStore(db).values(t) == DEFAULTS
    assert await audit(engine, t) == []


async def test_one_tenants_setting_does_not_reach_another(engine: AsyncEngine) -> None:
    db, a, b = TenantDb(engine), await tenant(engine), await tenant(engine)
    await PolicyStore(db).set(a, "stepUp", True, by=ADA, request_id="r1")
    assert (await PolicyStore(db).values(a))["stepUp"] is True
    assert await PolicyStore(db).values(b) == DEFAULTS


async def test_only_who_holds_settings_manage_changes_a_policy_and_the_change_is_served(signin: SignInRig) -> None:
    email = f"team.admin@{signin.zone}"
    await signin.person(email, role="admin")
    async with signin.engine.connect() as c:
        team = (await c.execute(sa.text("select team_id from members where email = :e"), {"e": email})).scalar_one()
    r = await signin.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    other = {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": team}
    assert (await signin.public.put("/v1/policies/stepUp", json={"value": True}, headers=other)).status_code == 403
    assert (await signin.public.get("/v1/policies", headers=other)).status_code == 200

    listed = await signin.public.get("/v1/policies", headers=signin.admin)
    assert {p["key"]: p["value"] for p in listed.json()["data"]} == DEFAULTS
    assert listed.json()["data"][0]["changedBy"] == "settings.manage"
    put = await signin.public.put("/v1/policies/stepUp", json={"value": True}, headers=signin.admin)
    assert put.status_code == 200, put.text
    assert put.json()["data"] | {"effect": ""} == {
        "key": "stepUp",
        "value": True,
        "default": False,
        "changedBy": "settings.manage",
        "effect": "",
        "kind": "bool",
        "title": "Step-up on every approval",
    }
    listed = await signin.public.get("/v1/policies", headers=signin.admin)
    assert {p["key"]: p["value"] for p in listed.json()["data"]} == {**DEFAULTS, "stepUp": True}
    assert ("policy.set", "stepUp", {"before": False, "after": True}) in await audit(signin.engine, signin.tenant)
    # A token minted after the change carries it, as does /me; services read the value there.
    again = await signin.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    # A token carries every policy but the ones decisions read live.
    in_token = {k: v for k, v in DEFAULTS.items() if not BY_KEY[k].live}
    assert again.json()["data"]["principal"]["policies"] == {**in_token, "stepUp": True}
    token = again.json()["data"]["token"]
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    assert claims["policies"] == {**in_token, "stepUp": True}
    me = await signin.public.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["data"]["policies"] == {**DEFAULTS, "stepUp": True}


async def test_a_key_or_value_the_catalogue_does_not_take_is_a_400(signin: SignInRig) -> None:
    for key, value in (("stepUp", 0.5), ("extractionFloor", 2), ("noSuchPolicy", True)):
        r = await signin.public.put(f"/v1/policies/{key}", json={"value": value}, headers=signin.admin)
        assert (r.status_code, r.json()["error"]["code"]) == (400, "policy_value"), r.text


async def test_a_team_admin_sets_memory_retention_and_a_service_reads_it_for_its_own_tenant(signin: SignInRig) -> None:
    email = f"team.admin@{signin.zone}"
    await signin.person(email, role="admin")
    async with signin.engine.connect() as c:
        team = (await c.execute(sa.text("select team_id from members where email = :e"), {"e": email})).scalar_one()
    r = await signin.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    admin = {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": team}
    # Not a security team admin, but memory retention is any team admin's (chat.manage); stepUp is not.
    assert (await signin.public.put("/v1/policies/stepUp", json={"value": True}, headers=admin)).status_code == 403
    put = await signin.public.put("/v1/policies/memoryRetentionDays", json={"value": 30}, headers=admin)
    assert put.status_code == 200 and put.json()["data"]["value"] == 30, put.text

    def service(scopes: list[str], tenant: str) -> dict[str, str]:
        token = mint_service_token(
            dev_service_signer(), service="agents", audience="platform", tenant_id=tenant, scopes=scopes
        )
        return {"Authorization": f"Bearer {token}"}

    got = await signin.public.get("/v1/policies/memoryRetentionDays", headers=service(["settings:view"], signin.tenant))
    assert got.status_code == 200 and got.json()["data"]["value"] == 30, got.text
    other = await signin.public.get("/v1/policies/memoryRetentionDays", headers=service(["settings:view"], "ten_other"))
    assert other.json()["data"]["value"] is None, "another tenant's value"
    bare = await signin.public.get("/v1/policies/memoryRetentionDays", headers=service([], signin.tenant))
    assert (bare.status_code, bare.json()["error"]["code"]) == (403, "scope_required")


async def _team_admin(signin: SignInRig, name: str, role: str = "admin") -> tuple[str, dict[str, str]]:
    email = f"{name}@{signin.zone}"
    await signin.person(email, role=role)
    async with signin.engine.connect() as c:
        team = (await c.execute(sa.text("select team_id from members where email = :e"), {"e": email})).scalar_one()
    r = await signin.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    return team, {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": team}


async def test_a_team_admin_sets_their_own_teams_publish_reviews_and_no_other_teams(signin: SignInRig) -> None:
    team_a, a = await _team_admin(signin, "ana")
    team_b, b = await _team_admin(signin, "ben")
    _, viewer = await _team_admin(signin, "vic", role="viewer")
    put = await signin.public.put("/v1/policies/publishReview", json={"value": {"agents": "always"}}, headers=a)
    assert put.status_code == 200, put.text
    assert put.json()["data"]["value"] == {team_a: {"agents": "always"}}
    put = await signin.public.put("/v1/policies/publishReview", json={"value": {"skills": "never"}}, headers=b)
    assert put.json()["data"]["value"] == {team_a: {"agents": "always"}, team_b: {"skills": "never"}}, put.text
    refused = await signin.public.put("/v1/policies/publishReview", json={"value": {"agents": "never"}}, headers=viewer)
    assert refused.status_code == 403, refused.text
    bad = await signin.public.put("/v1/policies/publishReview", json={"value": {"agents": "sometimes"}}, headers=a)
    assert (bad.status_code, bad.json()["error"]["code"]) == (400, "policy_value"), bad.text
    assert ("policy.set", "publishReview", {"before": None, "after": {"agents": "always"}}) in await audit(
        signin.engine, signin.tenant
    )
    # Read live on each decision, never from a token (owner, 2026-10-18): a token leaves it out, a service reads it.
    token = a["Authorization"].removeprefix("Bearer ")
    assert "publishReview" not in json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))["policies"]
    tools = mint_service_token(
        dev_service_signer(), service="tools", audience="platform", tenant_id=signin.tenant, scopes=["settings:view"]
    )
    live = await signin.public.get("/v1/policies/publishReview", headers={"Authorization": f"Bearer {tools}"})
    assert live.json()["data"]["value"][team_a] == {"agents": "always"}, live.text


async def test_only_the_security_team_lets_a_team_send_page_images(signin: SignInRig) -> None:
    """The page image leaves for the model provider (c-295): a team's own admin cannot turn it on for the team; a
    Security admin acting in that team can, and it applies to that team alone."""
    _, ana = await _team_admin(signin, "ana")
    refused = await signin.public.put("/v1/policies/pageImages", json={"value": True}, headers=ana)
    assert refused.status_code == 403, refused.text
    in_ops = {**signin.admin, "X-Team-Id": signin.ops_team}
    put = await signin.public.put("/v1/policies/pageImages", json={"value": True}, headers=in_ops)
    assert put.status_code == 200, put.text
    assert put.json()["data"]["value"] == {signin.ops_team: True}


async def test_every_member_reads_the_policies_and_only_the_cell_holder_changes_one(signin: SignInRig) -> None:
    # Policies are not secret (owner, 2026-10-18): a team admin and a viewer read every value; a change stays per cell.
    for name, role in (("tara", "admin"), ("val", "viewer")):
        _, who = await _team_admin(signin, name, role=role)
        listed = await signin.public.get("/v1/policies", headers=who)
        assert listed.status_code == 200, listed.text
        assert {p["key"]: p["value"] for p in listed.json()["data"]} == DEFAULTS
        one = await signin.public.get("/v1/policies/reviewSlaHours", headers=who)
        assert one.status_code == 200 and one.json()["data"]["value"] == 8, one.text
    refused = await signin.public.put("/v1/policies/reviewSlaHours", json={"value": 4}, headers=who)
    assert refused.status_code == 403, refused.text


async def test_every_policy_says_how_it_is_drawn_and_what_it_is_called(signin: SignInRig) -> None:
    """The Policies page draws each row from its kind and title (c-224): a policy added without them would show as a
    blank row or be guessed from its value's shape."""
    rows = (await signin.public.get("/v1/policies", headers=signin.admin)).json()["data"]
    assert {r["key"]: r["kind"] for r in rows} == {p.key: p.kind for p in POLICIES}
    assert all(r["kind"] in KINDS and r["title"] for r in rows), rows
