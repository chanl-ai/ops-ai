"""Who in a team holds an action (GET /v1/access/holders, c-186), what a "View only" notice names, by failure mode: a
holder in another team named, a workspace admin (`*`) left out, an expired grant still counted, a caller reading a
team they are not in, and a cell outside the catalogue answered."""

from __future__ import annotations

from typing import Any

from ops_platform.store.roles import mirror_membership
from ops_platform.store.tables import members, users
from ops_service_kit.ids import new_id, now_iso

from .conftest import Person, Platform
from .test_permissions import grant


async def join(platform: Platform, tenant: str, team: str, email: str, role: str) -> str:
    """A second person, active in `team` with the membership `role`, as the member routes would write them."""
    now, user = now_iso(), new_id("usr")
    async with platform.engine.begin() as c:
        await c.execute(
            users.insert().values(id=user, tenant_id=tenant, email=email, name=email, status="active", created_at=now)
        )
        await c.execute(
            members.insert().values(
                id=new_id("mem"),
                tenant_id=tenant,
                team_id=team,
                user_id=user,
                email=email,
                role=role,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        await mirror_membership(
            c,
            tenant_id=tenant,
            team_id=team,
            user_id=user,
            member_role=role,
            security_team="team_security",
            granted_by="test",
            at=now,
        )
    return user


async def ask(platform: Platform, p: Person, team: str, area: str, action: str) -> tuple[int, dict[str, Any]]:
    token = (await platform.sign_in(p)).json()["data"]["token"]
    r = await platform.public.get(
        "/v1/access/holders",
        params={"area": area, "action": action},
        headers={"Authorization": f"Bearer {token}", "X-Team-Id": team},
    )
    body: dict[str, Any] = r.json()
    return r.status_code, body


async def test_a_viewer_learns_which_roles_edit_agents_and_who_holds_them_in_their_team(platform: Platform) -> None:
    viewer = await platform.person(roles=("viewer",))
    team = next(iter(viewer.teams))
    builder = await join(platform, viewer.tenant_id, team, f"{new_id('b')}@bank.test", "builder")
    other_team_builder = await platform.person(roles=("builder",), tenant_id=viewer.tenant_id)
    workspace_admin = await platform.person(roles=("viewer",), tenant_id=viewer.tenant_id)
    await grant(platform, workspace_admin, "*", "admin")
    lapsed = await platform.person(roles=("viewer",), tenant_id=viewer.tenant_id)
    await grant(platform, lapsed, team, "builder", expires_at="2020-01-01T00:00:00.000Z")

    status, body = await ask(platform, viewer, team, "agents", "edit")
    assert status == 200, body
    data: dict[str, Any] = body["data"]
    roles: list[dict[str, str]] = data["roles"]
    holders: list[dict[str, Any]] = data["holders"]
    assert data["teamId"] == team
    assert {"builder", "admin"} <= {r["id"] for r in roles} and "viewer" not in {r["id"] for r in roles}
    ids = {str(h["id"]) for h in holders}
    assert builder in ids, "the team's builder"
    assert workspace_admin.user_id in ids, "an admin of every team"
    assert other_team_builder.user_id not in ids, "a builder of another team"
    assert lapsed.user_id not in ids and viewer.user_id not in ids


async def test_a_team_the_caller_is_not_in_and_an_unknown_cell_are_refused(platform: Platform) -> None:
    viewer = await platform.person(roles=("viewer",))
    stranger_team = next(iter((await platform.person(roles=("builder",), tenant_id=viewer.tenant_id)).teams))
    status, _ = await ask(platform, viewer, stranger_team, "agents", "edit")
    assert status in (400, 403), "the token does not name that team"
    status, body = await ask(platform, viewer, next(iter(viewer.teams)), "agents", "fly")
    assert (status, body["error"]["code"]) == (400, "unknown_cell")


async def test_holders_of_a_records_team_name_that_teams_people_and_only_for_its_members(platform: Platform) -> None:
    """A View only notice on another team's record (the console passes the record's team): the holders are that team's,
    never the acting team's, and a person outside that team learns nothing."""
    viewer = await platform.person(roles=("viewer",))
    home = next(iter(viewer.teams))
    builder = await platform.person(roles=("builder",), tenant_id=viewer.tenant_id)
    record_team = next(iter(builder.teams))
    await join_existing(platform, viewer, record_team, "viewer")
    token = (await platform.sign_in(viewer)).json()["data"]["token"]
    auth = {"Authorization": f"Bearer {token}", "X-Team-Id": home}
    q = {"area": "agents", "action": "edit", "team": record_team}
    r = await platform.public.get("/v1/access/holders", params=q, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["teamId"] == record_team
    ids = {h["id"] for h in r.json()["data"]["holders"]}
    assert builder.user_id in ids and viewer.user_id not in ids

    outsider = await platform.person(roles=("viewer",), tenant_id=viewer.tenant_id)
    token = (await platform.sign_in(outsider)).json()["data"]["token"]
    auth = {"Authorization": f"Bearer {token}", "X-Team-Id": next(iter(outsider.teams))}
    refused = await platform.public.get("/v1/access/holders", params=q, headers=auth)
    assert (refused.status_code, refused.json()["error"]["code"]) == (403, "team_forbidden"), refused.text


async def join_existing(platform: Platform, p: Person, team: str, role: str) -> None:
    """An existing person made an active member of a second team."""
    now = now_iso()
    async with platform.engine.begin() as c:
        await c.execute(
            members.insert().values(
                id=new_id("mem"),
                tenant_id=p.tenant_id,
                team_id=team,
                user_id=p.user_id,
                email=p.email,
                role=role,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        await mirror_membership(
            c,
            tenant_id=p.tenant_id,
            team_id=team,
            user_id=p.user_id,
            member_role=role,
            security_team="team_security",
            granted_by="test",
            at=now,
        )
