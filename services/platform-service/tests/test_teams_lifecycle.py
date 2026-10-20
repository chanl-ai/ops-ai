"""Teams as workspace admins manage them (c-198), by failure mode: a member who is not a workspace admin creates,
renames, archives, restores or lists every team (F1); two teams share a name in another case (F2); an archived team
keeps acting in tokens, the switcher, a team admin's rights or new invitations (F3); a team is made with no admin or one
from another workspace (F4); another workspace's team is changed by id (F5); the Security team is archived (F6)."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from ops_platform.keys import dev_signer
from ops_platform.store.tables import members, teams
from ops_policy import Ed25519Verifier, verify
from ops_service_kit.ids import new_id, now_iso

from .conftest import DEMO_PASSWORD, SignInRig


async def _session(rig: SignInRig, email: str) -> dict[str, Any]:
    r = await rig.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _h(session: dict[str, Any], team: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['token']}", "X-Team-Id": team}


async def _team_of(rig: SignInRig, user_id: str) -> str:
    async with rig.engine.connect() as c:
        return str((await c.execute(sa.select(members.c.team_id).where(members.c.user_id == user_id))).scalar_one())


async def _create(rig: SignInRig, name: str, admin: str, headers: dict[str, str] | None = None) -> Any:
    return await rig.public.post(
        "/v1/settings/teams", json={"name": name, "admin": admin}, headers=headers or rig.admin
    )


async def test_a_workspace_admin_creates_a_team_whose_first_admin_gets_it_in_the_next_token(signin: SignInRig) -> None:
    await signin.person(f"lead@{signin.zone}", role="viewer")
    r = await _create(signin, "Lending", f"LEAD@{signin.zone}")
    assert r.status_code == 201, r.text
    team = r.json()["data"]
    assert (team["name"], team["memberCount"], team["adminCount"], team["status"]) == ("Lending", 1, 1, "active")
    claims = verify(
        (await _session(signin, f"lead@{signin.zone}"))["token"],
        Ed25519Verifier.from_jwk(dev_signer().public_jwk(), "platform"),
    )
    assert claims["roles"][team["id"]] == "admin"  # type: ignore[index]
    listed = await signin.public.get("/v1/settings/teams", params={"search": "lend"}, headers=signin.admin)
    assert [t["id"] for t in listed.json()["data"]["data"]] == [team["id"]]
    assert listed.json()["data"]["pagination"]["total"] == 1


async def test_only_a_workspace_admin_manages_or_lists_teams(signin: SignInRig) -> None:
    # An admin of their own team, outside the Security team.
    boss = await signin.person(f"boss@{signin.zone}", role="admin")
    own = await _team_of(signin, boss)
    h = _h(await _session(signin, f"boss@{signin.zone}"), own)
    assert (await _create(signin, "Treasury", f"boss@{signin.zone}", headers=h)).status_code == 403
    assert (await signin.public.get("/v1/settings/teams", headers=h)).status_code == 403
    assert (await signin.public.patch(f"/v1/settings/teams/{own}", json={"name": "Mine"}, headers=h)).status_code == 403
    assert (await signin.public.post(f"/v1/settings/teams/{own}/archive", headers=h)).status_code == 403
    assert (await signin.public.post(f"/v1/settings/teams/{own}/restore", headers=h)).status_code == 403


async def test_a_security_admin_who_is_not_a_workspace_admin_cannot_create_a_team(signin: SignInRig) -> None:
    """Admin of the Security team (settings.manage) but holding no role in every team: not a workspace admin."""
    h = await signin.security_admin_only(f"sec@{signin.zone}")
    assert (await _create(signin, "Payments", f"sec@{signin.zone}", headers=h)).status_code == 403
    assert (await signin.public.get("/v1/settings/teams", headers=h)).status_code == 403


async def test_a_name_is_unique_in_any_case_within_the_workspace_only(signin: SignInRig) -> None:
    await signin.person(f"cards@{signin.zone}", role="viewer")
    lead = f"cards@{signin.zone}"
    assert (await _create(signin, "Cards", lead)).status_code == 201
    clash = await _create(signin, "  cARDS ", lead)
    assert clash.status_code in (400, 409)
    clash = await _create(signin, "cARDS", lead)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "team_name_taken"
    other = new_id("ten")
    async with signin.engine.begin() as c:
        await c.execute(
            sa.text(
                "insert into tenants (id, name, status, allowed_domains, created_at) "
                "values (:t, :t, 'active', '[]', :n)"
            ),
            {"t": other, "n": now_iso()},
        )
        await c.execute(
            teams.insert().values(
                id=new_id("team"), tenant_id=other, name="Wealth", owner_groups=[], scope="owned", created_at=now_iso()
            )
        )
    assert (await _create(signin, "Wealth", lead)).status_code == 201


async def test_an_archived_team_leaves_tokens_rights_and_invitations_until_restored(signin: SignInRig) -> None:
    await signin.person(f"arch@{signin.zone}", role="viewer")
    team = (await _create(signin, "Archive me", f"arch@{signin.zone}")).json()["data"]["id"]
    before = await _session(signin, f"arch@{signin.zone}")
    assert team in before["principal"]["teamIds"]
    r = await signin.public.post(f"/v1/settings/teams/{team}/archive", headers=signin.admin)
    assert r.status_code == 200 and r.json()["data"]["status"] == "archived", r.text
    after = await _session(signin, f"arch@{signin.zone}")
    assert team not in after["principal"]["teamIds"]
    mine = await signin.public.get("/v1/teams", headers={"Authorization": f"Bearer {after['token']}"})
    assert team not in [t["id"] for t in mine.json()["data"]]
    # The token minted before the archive still names the team; its admin right there is read from the database.
    invite = await signin.public.post(
        "/v1/settings/members/invite",
        json={"emails": [f"new@{signin.zone}"], "role": "viewer"},
        headers=_h(before, team),
    )
    assert invite.status_code in (403, 409), invite.text
    assert (await signin.public.post(f"/v1/settings/teams/{team}/restore", headers=signin.admin)).status_code == 200
    again = await _session(signin, f"arch@{signin.zone}")
    assert team in again["principal"]["teamIds"]


async def test_a_team_needs_a_first_admin_from_this_workspace(signin: SignInRig) -> None:
    assert (await _create(signin, "Nobody leads", f"nobody@{signin.zone}")).status_code == 404
    other = new_id("ten")
    stranger = new_id("usr")
    async with signin.engine.begin() as c:
        await c.execute(
            sa.text(
                "insert into tenants (id, name, status, allowed_domains, created_at) "
                "values (:t, :t, 'active', '[]', :n)"
            ),
            {"t": other, "n": now_iso()},
        )
        await c.execute(
            sa.text(
                "insert into users (id, tenant_id, email, name, status, created_at) "
                "values (:u, :t, 'x@other.test', 'X', 'active', :n)"
            ),
            {"u": stranger, "t": other, "n": now_iso()},
        )
    assert (await _create(signin, "Borrowed lead", "x@other.test")).status_code == 404
    listed = await signin.public.get("/v1/settings/teams", params={"search": "lead"}, headers=signin.admin)
    assert listed.json()["data"]["data"] == []


async def test_another_workspaces_team_answers_404_and_the_security_team_stays(signin: SignInRig) -> None:
    other, theirs = new_id("ten"), new_id("team")
    async with signin.engine.begin() as c:
        await c.execute(
            sa.text(
                "insert into tenants (id, name, status, allowed_domains, created_at) "
                "values (:t, :t, 'active', '[]', :n)"
            ),
            {"t": other, "n": now_iso()},
        )
        await c.execute(
            teams.insert().values(
                id=theirs, tenant_id=other, name="Theirs", owner_groups=[], scope="owned", created_at=now_iso()
            )
        )
    assert (
        await signin.public.patch(f"/v1/settings/teams/{theirs}", json={"name": "Ours"}, headers=signin.admin)
    ).status_code == 404
    assert (await signin.public.post(f"/v1/settings/teams/{theirs}/archive", headers=signin.admin)).status_code == 404
    r = await signin.public.post(f"/v1/settings/teams/{signin.security_team}/archive", headers=signin.admin)
    assert r.status_code == 409 and r.json()["error"]["code"] == "security_team"
