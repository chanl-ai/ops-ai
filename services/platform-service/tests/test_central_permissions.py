"""Permission decisions that go through the one central check, by failure mode: a team's Admin outside the Security
team cannot change their own team's approval rule, or can change another team's, or sets what stays Security's; a
Chat user reads the roles of the workspace; a custom role holding access.manage is linked to an existing person by the
email a provider asserts on a first SSO sign-in."""

from __future__ import annotations

import sqlalchemy as sa

from ops_platform.store.tables import role_assignments, signin_identities
from ops_service_kit.ids import new_id, now_iso

from .conftest import SignInRig
from .test_policies import _team_admin  # pyright: ignore[reportPrivateUsage]

SALESFORCE = "plugin:opsai.salesforce"


async def test_a_team_admin_outside_security_sets_their_own_teams_approval_rule_and_no_one_elses(
    signin: SignInRig,
) -> None:
    team_b, b = await _team_admin(signin, "bella")
    team_c, c = await _team_admin(signin, "carl")
    put = await signin.public.put(
        "/v1/policies/appChanges", json={"value": {"ask": True, "answer": "person"}}, headers=b
    )
    assert put.status_code == 200, put.text
    assert list(put.json()["data"]["value"]) == [team_b]
    # Acting in team C with a role held in team B changes nothing of team C's.
    other = await signin.public.put(
        "/v1/policies/appChanges",
        json={"value": {"ask": True, "answer": "person"}},
        headers={**b, "X-Team-Id": team_c},
    )
    assert other.status_code == 403, other.text
    # What E03 keeps with the Security team stays there.
    images = await signin.public.put("/v1/policies/pageImages", json={"value": True}, headers=b)
    assert images.status_code == 403, images.text
    assert (await signin.public.get("/v1/policies/appChanges", headers=c)).json()["data"]["value"].get(team_c) is None


async def test_a_chat_user_reads_no_roles_but_every_member_still_reads_the_policies(signin: SignInRig) -> None:
    _, chat = await _team_admin(signin, "cleo", role="chat_user")
    roles = await signin.public.get("/v1/roles", headers=chat)
    assert roles.status_code == 403, roles.text
    assert (await signin.public.get("/v1/policies/appChanges", headers=chat)).status_code == 200


async def test_a_first_sso_sign_in_never_links_a_person_holding_access_manage_through_a_custom_role(
    signin: SignInRig,
) -> None:
    role = await signin.public.post(
        "/v1/roles",
        headers=signin.admin,
        json={"name": "People desk", "permissions": [{"area": "access", "action": "manage", "scope": "all"}]},
    )
    assert role.status_code == 201, role.text
    await signin.saml(f"desk.{signin.zone}")
    user = await signin.person(f"lead@desk.{signin.zone}", role="viewer")
    async with signin.engine.begin() as c:
        team = (await c.execute(sa.text("select team_id from members where user_id = :u"), {"u": user})).scalar_one()
        await c.execute(
            role_assignments.insert().values(
                id=new_id("ras"), tenant_id=signin.tenant, subject_kind="person", subject_id=user,
                role_id=role.json()["data"]["id"], team_id=team, expires_at=None, granted_by="test",
                reason="test grant", source="grant", created_at=now_iso(),
            )
        )  # fmt: skip
    refused = await signin.sign_in_sso(f"lead@desk.{signin.zone}")
    assert refused.query == {"error": "no_access"} and refused.completed is None
    async with signin.engine.begin() as c:
        count = sa.select(sa.func.count()).where(signin_identities.c.user_id == user)
        assert (await c.execute(count)).scalar_one() == 0
