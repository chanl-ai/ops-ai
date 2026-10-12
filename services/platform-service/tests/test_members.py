"""Me, teams, members and invites (P5 to P10, P13), by failure mode: a team the caller is not in, a non-admin writing,
the last admin demoted or removed (I6), a removed member's sessions and keys still working (I10), an invite that is
expired, used, or from a domain the tenant does not allow, and a body naming a tenant or team (I1, I5)."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from ops_platform.store.tables import audit_entries, members, tenants

from .conftest import SERVICE, Person, Platform


async def bearer(platform: Platform, p: Person) -> dict[str, str]:
    r = await platform.sign_in(p)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def team_of(p: Person, role: str = "admin") -> str:
    return next(t for t, r in p.teams.items() if r == role)


async def as_admin(platform: Platform) -> tuple[Person, dict[str, str]]:
    p = await platform.person(roles=("admin",))
    return p, {**(await bearer(platform, p)), "X-Team-Id": team_of(p)}


async def join(platform: Platform, admin: Person, role: str) -> Person:
    """Another person in the admin's tenant, an active member of the admin's team with `role`."""
    other = await platform.person(roles=(), tenant_id=admin.tenant_id)
    team = team_of(admin)
    async with platform.engine.begin() as c:
        await c.execute(
            members.insert().values(
                id=f"mem_{other.user_id}",
                tenant_id=admin.tenant_id,
                team_id=team,
                user_id=other.user_id,
                email=other.email,
                role=role,
                status="active",
                created_at="2026-01-01T00:00:00.000Z",
                updated_at="2026-01-01T00:00:00.000Z",
            )
        )
    other.teams[team] = role
    return other


async def member_rows(platform: Platform, h: dict[str, str], **params: Any) -> list[dict[str, Any]]:
    r = await platform.public.get("/v1/settings/members", headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()["data"]["data"]


async def test_me_names_the_user_and_every_team_with_its_role(platform: Platform) -> None:
    p = await platform.person(roles=("admin", "viewer"))
    r = await platform.public.get("/v1/me", headers=await bearer(platform, p))
    assert r.status_code == 200, r.text
    me = r.json()["data"]
    assert me["user"]["id"] == p.user_id and me["tenantId"] == p.tenant_id
    assert {t["id"]: t["role"] for t in me["teams"]} == p.teams


async def test_teams_lists_only_the_callers_teams(platform: Platform) -> None:
    p = await platform.person(roles=("builder",))
    await platform.person(roles=("admin",), tenant_id=p.tenant_id)
    r = await platform.public.get("/v1/teams", headers=await bearer(platform, p))
    assert r.status_code == 200, r.text
    assert [t["id"] for t in r.json()["data"]] == list(p.teams)
    assert r.json()["data"][0]["memberCount"] == 1


async def test_a_team_header_outside_the_token_is_403_and_absent_with_several_is_400(platform: Platform) -> None:
    p = await platform.person(roles=("admin", "viewer"))
    stranger = await platform.person(roles=("admin",), tenant_id=p.tenant_id)
    h = await bearer(platform, p)
    r = await platform.public.get("/v1/settings/members", headers={**h, "X-Team-Id": team_of(stranger)})
    assert r.status_code == 403 and r.json()["error"]["code"] == "team_forbidden"
    r = await platform.public.get("/v1/settings/members", headers=h)
    assert r.status_code == 400 and r.json()["error"]["code"] == "team_required"


async def test_one_team_is_selected_without_a_header(platform: Platform) -> None:
    p = await platform.person(roles=("admin",))
    rows = await member_rows(platform, await bearer(platform, p))
    assert [m["email"] for m in rows] == [p.email]


async def test_members_lists_the_current_team_only_and_filters(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    viewer = await join(platform, admin, "viewer")
    await platform.person(roles=("admin",), tenant_id=admin.tenant_id)  # another team, same tenant
    rows = await member_rows(platform, h)
    assert sorted(m["email"] for m in rows) == sorted([admin.email, viewer.email])
    assert [m["email"] for m in await member_rows(platform, h, role="viewer")] == [viewer.email]
    assert all(m["teamId"] == team_of(admin) and m["team"] for m in rows)


async def test_only_an_admin_invites_changes_roles_or_removes(platform: Platform) -> None:
    admin, _ = await as_admin(platform)
    builder = await join(platform, admin, "builder")
    h = {**(await bearer(platform, builder)), "X-Team-Id": team_of(admin)}
    for path, body in (
        ("invite", {"emails": ["a@bank.test"], "role": "viewer"}),
        ("role", {"ids": ["mem_x"], "role": "viewer"}),
        ("delete", {"ids": ["mem_x"]}),
    ):
        r = await platform.public.post(f"/v1/settings/members/{path}", headers=h, json=body)
        assert r.status_code == 403, path


async def test_invite_creates_invited_members_and_skips_existing_ones(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    body = {"emails": ["new.one@bank.test", "New.Two@bank.test", admin.email], "role": "approver"}
    r = await platform.public.post("/v1/settings/members/invite", headers=h, json=body)
    assert r.status_code == 200, r.text
    result = r.json()["data"]
    assert len(result["updated"]) == 2 and [s["reason"] for s in result["skipped"]] == ["already_member"]
    assert sorted(i["email"] for i in result["invites"]) == ["new.one@bank.test", "new.two@bank.test"]
    invited = await member_rows(platform, h, status="invited")
    assert sorted(m["email"] for m in invited) == ["new.one@bank.test", "new.two@bank.test"]
    assert all(m["role"] == "approver" for m in invited)


async def test_the_last_admin_is_skipped_with_a_reason(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    [me] = [m for m in await member_rows(platform, h) if m["email"] == admin.email]
    r = await platform.public.post("/v1/settings/members/role", headers=h, json={"ids": [me["id"]], "role": "viewer"})
    assert r.json()["data"] == {"updated": [], "skipped": [{"id": me["id"], "reason": "last_admin"}]}
    r = await platform.public.post("/v1/settings/members/delete", headers=h, json={"ids": [me["id"]]})
    assert r.json()["data"] == {"updated": [], "skipped": [{"id": me["id"], "reason": "last_admin"}]}


async def test_demoting_both_of_two_admins_keeps_one(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    await join(platform, admin, "admin")
    ids = [m["id"] for m in await member_rows(platform, h, role="admin")]
    r = await platform.public.post("/v1/settings/members/role", headers=h, json={"ids": ids, "role": "builder"})
    result = r.json()["data"]
    assert len(result["updated"]) == 1 and result["skipped"][0]["reason"] == "last_admin"
    assert len(await member_rows(platform, h, role="admin")) == 1


async def test_a_role_change_applies(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    viewer = await join(platform, admin, "viewer")
    [row] = await member_rows(platform, h, role="viewer")
    r = await platform.public.post(
        "/v1/settings/members/role", headers=h, json={"ids": [row["id"]], "role": "approver"}
    )
    assert r.json()["data"]["updated"] == [row["id"]]
    assert [m["email"] for m in await member_rows(platform, h, role="approver")] == [viewer.email]


async def test_removing_a_member_ends_their_sessions_and_disables_their_keys(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    builder = await join(platform, admin, "builder")
    signed_in = (await platform.sign_in(builder)).json()["data"]
    key = await platform.api_key(builder)
    [row] = await member_rows(platform, h, role="builder")
    r = await platform.public.post("/v1/settings/members/delete", headers=h, json={"ids": [row["id"]]})
    assert r.json()["data"]["updated"] == [row["id"]]
    assert builder.email not in [m["email"] for m in await member_rows(platform, h)]
    auth = {"Authorization": f"Bearer {signed_in['token']}"}
    assert (await platform.public.get("/v1/auth/session", headers=auth)).status_code == 401
    refreshed = await platform.public.post("/v1/auth/refresh", json={"refreshToken": signed_in["refreshToken"]})
    assert refreshed.status_code == 401
    r = await platform.internal.post("/v1/auth/introspect", json={"apiKey": key}, headers=SERVICE)
    assert r.status_code == 401


async def invite_one(platform: Platform, h: dict[str, str], email: str, role: str = "builder") -> str:
    r = await platform.public.post("/v1/settings/members/invite", headers=h, json={"emails": [email], "role": role})
    return r.json()["data"]["invites"][0]["token"]


async def test_an_invite_reads_without_signing_in(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    token = await invite_one(platform, h, "reader@bank.test")
    r = await platform.public.get(f"/v1/invites/{token}")
    assert r.status_code == 200, r.text
    preview = r.json()["data"]
    assert preview["email"] == "reader@bank.test" and preview["role"] == "builder"
    assert preview["teamId"] == team_of(admin) and preview["state"] == "pending"
    assert (await platform.public.get("/v1/invites/inv_notarealtokenatall")).status_code == 404


async def test_accepting_returns_a_token_that_already_carries_the_team(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    token = await invite_one(platform, h, "joiner@bank.test")
    r = await platform.public.post(f"/v1/invites/{token}/accept", json={"name": "Jo Iner"})
    assert r.status_code == 200, r.text
    session = r.json()["data"]
    assert session["principal"]["teamIds"] == [team_of(admin)]
    assert session["principal"]["roles"] == {team_of(admin): "builder"}
    joined = [m for m in await member_rows(platform, h) if m["email"] == "joiner@bank.test"]
    assert joined[0]["status"] == "active" and joined[0]["name"] == "Jo Iner"
    again = await platform.public.post(f"/v1/invites/{token}/accept", json={"name": "Jo Iner"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "invite_used"
    assert (await platform.public.get(f"/v1/invites/{token}")).json()["data"]["state"] == "accepted"


async def test_an_expired_invite_reads_as_expired_and_cannot_be_accepted(platform: Platform) -> None:
    _admin, h = await as_admin(platform)
    token = await invite_one(platform, h, "late@bank.test")
    async with platform.engine.begin() as c:
        await c.execute(
            members.update()
            .where(members.c.email == "late@bank.test")
            .values(invite_expires_at="2020-01-01T00:00:00.000Z")
        )
    assert (await platform.public.get(f"/v1/invites/{token}")).json()["data"]["state"] == "expired"
    r = await platform.public.post(f"/v1/invites/{token}/accept", json={"name": "Late"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invite_expired"


async def test_an_invite_from_a_domain_the_tenant_does_not_allow_is_refused(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    async with platform.engine.begin() as c:
        await c.execute(tenants.update().where(tenants.c.id == admin.tenant_id).values(allowed_domains=["bank.test"]))
    token = await invite_one(platform, h, "outsider@elsewhere.test")
    r = await platform.public.post(f"/v1/invites/{token}/accept", json={"name": "Out Sider"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "domain_not_allowed"


async def test_a_body_naming_a_tenant_or_team_is_refused(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    for body in (
        {"emails": ["x@bank.test"], "role": "viewer", "teamId": "team_other"},
        {"emails": ["x@bank.test"], "role": "viewer", "tenantId": admin.tenant_id},
        {"emails": ["x@bank.test"], "role": "owner"},
    ):
        r = await platform.public.post("/v1/settings/members/invite", headers=h, json=body)
        assert r.status_code == 400, body


async def test_member_writes_are_audited(platform: Platform) -> None:
    _admin, h = await as_admin(platform)
    token = await invite_one(platform, h, "audited@bank.test")
    await platform.public.post(f"/v1/invites/{token}/accept", json={"name": "Aud Ited"})
    [row] = [m for m in await member_rows(platform, h) if m["email"] == "audited@bank.test"]
    await platform.public.post("/v1/settings/members/role", headers=h, json={"ids": [row["id"]], "role": "viewer"})
    await platform.public.post("/v1/settings/members/delete", headers=h, json={"ids": [row["id"]]})
    async with platform.engine.connect() as c:
        actions = (
            (
                await c.execute(
                    sa.select(audit_entries.c.action)
                    .where(audit_entries.c.target_id == row["id"])
                    .order_by(audit_entries.c.at)
                )
            )
            .scalars()
            .all()
        )
    assert list(actions) == ["member.invite", "member.accept", "member.role", "member.remove"]
