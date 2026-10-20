"""Roles and what a person may do (c-147), by failure mode: two roles in one team showing only one role's actions, an
expired assignment still granting, a role change through the member routes leaving the old role's actions in place or
the token's permission version unchanged, and another person's permissions readable without a shared team."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
import sqlalchemy as sa

from ops_access import ACTIONS, AREAS, BUILTIN_ROLES, can
from ops_identity import Identity
from ops_platform.store.roles import mirror_membership
from ops_platform.store.tables import members, role_assignments
from ops_service_kit.errors import Forbidden
from ops_service_kit.ids import new_id, now_iso

from .conftest import Person, Platform


async def bearer(platform: Platform, p: Person) -> dict[str, str]:
    r = await platform.sign_in(p)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def claims(headers: dict[str, str]) -> dict[str, Any]:
    payload = headers["Authorization"].split(" ")[1].split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


async def join(platform: Platform, p: Person, team: str, role: str) -> None:
    """Makes `p` an active `role` member of `team`, with the assignments the member routes write."""
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
                created_at=now_iso(),
                updated_at=now_iso(),
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
            at=now_iso(),
        )
    p.teams[team] = role


async def grant(platform: Platform, p: Person, team: str, role_id: str, *, expires_at: str | None = None) -> None:
    async with platform.engine.begin() as c:
        await c.execute(
            role_assignments.insert().values(
                id=new_id("ras"),
                tenant_id=p.tenant_id,
                subject_kind="person",
                subject_id=p.user_id,
                role_id=role_id,
                team_id=team,
                expires_at=expires_at,
                granted_by="test",
                reason="test grant",
                source="grant",
                created_at=now_iso(),
            )
        )


async def permissions(platform: Platform, h: dict[str, str], path: str = "/v1/me/permissions") -> dict[str, Any]:
    r = await platform.public.get(path, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def held(view: dict[str, Any], team: str) -> dict[str, dict[str, Any]]:
    teams: list[dict[str, Any]] = view["teams"]
    none: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = next((t["permissions"] for t in teams if t["teamId"] == team), none)
    return {f"{p['area']}.{p['action']}": p for p in rows}


async def test_roles_lists_the_five_builtin_roles_with_their_grids(platform: Platform) -> None:
    p = await platform.person(roles=("viewer",))
    h = await bearer(platform, p)
    r = await platform.public.get("/v1/roles", headers=h)
    assert r.status_code == 200, r.text
    listed = {x["id"]: x for x in r.json()["data"]}
    assert list(listed) == [b.id for b in BUILTIN_ROLES]
    assert listed["viewer"]["assignmentCount"] == 1
    r = await platform.public.get("/v1/roles/admin", headers=h)
    assert r.status_code == 200, r.text
    admin = r.json()["data"]
    assert len(admin["permissions"]) == admin["permissionCount"] == len(BUILTIN_ROLES[0].grants)
    assert [row["area"] for row in admin["grid"]] == list(AREAS)
    assert set(admin["grid"][0]["actions"]) == set(ACTIONS)
    assert admin["grid"][AREAS.index("audit")]["actions"]["view"] == "all"
    # Admins hold every cell (owner, 2026-10-17); settings.manage is still checked in the Security team.
    assert admin["grid"][AREAS.index("settings")]["actions"]["manage"] == "all"
    assert (await platform.public.get("/v1/roles/nope", headers=h)).status_code == 404


async def test_two_roles_in_one_team_add_up(platform: Platform) -> None:
    p = await platform.person(roles=("builder",))
    team = next(iter(p.teams))
    await grant(platform, p, team, "reviewer")
    mine = held(await permissions(platform, await bearer(platform, p)), team)
    assert mine["agents.create"]["roles"] == [{"id": "builder", "name": "Builder", "via": "person"}]
    assert mine["agents.decide"]["roles"] == [{"id": "reviewer", "name": "Reviewer", "via": "person"}]
    assert {r["id"] for r in mine["agents.view"]["roles"]} == {"builder", "reviewer"}
    # Builder deletes only its own skills, Reviewer cancels any run: the wider scope wins across the two.
    assert mine["cases.manage"]["scope"] == "all"


async def test_an_expired_assignment_grants_nothing(platform: Platform) -> None:
    p = await platform.person(roles=("viewer",))
    team = next(iter(p.teams))
    await grant(platform, p, team, "builder", expires_at="2020-01-01T00:00:00.000Z")
    mine = held(await permissions(platform, await bearer(platform, p)), team)
    assert "agents.create" not in mine
    await grant(platform, p, team, "reviewer", expires_at="2999-01-01T00:00:00.000Z")
    mine = held(await permissions(platform, await bearer(platform, p)), team)
    assert "agents.decide" in mine


async def test_a_role_change_moves_the_assignment_and_the_version(platform: Platform) -> None:
    admin = await platform.person(roles=("admin",))
    team = next(iter(admin.teams))
    other = await platform.person(roles=(), tenant_id=admin.tenant_id)
    await join(platform, other, team, "builder")
    before = await bearer(platform, other)
    assert "agents.create" in held(await permissions(platform, before), team)
    ah = {**(await bearer(platform, admin)), "X-Team-Id": team}
    rows = (await platform.public.get("/v1/settings/members", headers=ah)).json()["data"]["data"]
    member = next(m["id"] for m in rows if m["email"] == other.email)
    r = await platform.public.post("/v1/settings/members/role", headers=ah, json={"ids": [member], "role": "viewer"})
    assert r.json()["data"]["updated"] == [member], r.text
    after = await bearer(platform, other)
    mine = held(await permissions(platform, after), team)
    assert "agents.create" not in mine
    assert mine["agents.view"]["roles"] == [{"id": "viewer", "name": "Viewer", "via": "person"}]
    assert claims(after)["perm_version"] > claims(before)["perm_version"]
    r = await platform.public.post("/v1/settings/members/delete", headers=ah, json={"ids": [member]})
    assert r.json()["data"]["updated"] == [member], r.text
    async with platform.engine.connect() as c:
        left = await c.execute(
            sa.select(sa.func.count())
            .select_from(role_assignments)
            .where(role_assignments.c.subject_id == other.user_id, role_assignments.c.team_id == team)
        )
        assert left.scalar_one() == 0


async def test_another_persons_permissions_show_only_shared_teams(platform: Platform) -> None:
    me = await platform.person(roles=("viewer", "builder"))
    shared, mine_only = list(me.teams)
    other = await platform.person(roles=("admin",), tenant_id=me.tenant_id)
    await join(platform, other, shared, "approver")
    h = await bearer(platform, me)
    view = await permissions(platform, h, f"/v1/people/{other.user_id}/permissions")
    assert [t["teamId"] for t in view["teams"]] == [shared]
    assert "agents.decide" in held(view, shared)
    stranger = await platform.person(roles=("admin",), tenant_id=me.tenant_id)
    r = await platform.public.get(f"/v1/people/{stranger.user_id}/permissions", headers=h)
    assert r.status_code == 404, r.text
    elsewhere = await platform.person(roles=("admin",))
    r = await platform.public.get(f"/v1/people/{elsewhere.user_id}/permissions", headers=h)
    assert r.status_code == 404, r.text
    assert mine_only not in [t["teamId"] for t in view["teams"]]


class _Post:
    method = "POST"


async def test_a_platform_token_decides_through_ops_access(platform: Platform) -> None:
    """The real seam: sign in, resolve the token as a service does, and ask `can`. An expired grant is left off."""
    p = await platform.person(roles=("viewer",))
    team = next(iter(p.teams))
    await grant(platform, p, team, "builder", expires_at="2020-01-01T00:00:00.000Z")
    await grant(platform, p, team, "reviewer")
    h = await bearer(platform, p)
    assert claims(h)["access"] == {team: ["viewer", "reviewer"]}

    async def jwks() -> dict[str, Any]:
        return {"keys": [platform.signer.public_jwk()]}

    async def no_keys(_key: str) -> dict[str, Any] | None:
        return None

    identity = Identity(audience="agents", jwks=jwks, introspect=no_keys)
    who = await identity.principal(_Post(), authorization=h["Authorization"], x_team_id=team)  # pyright: ignore[reportArgumentType]
    assert can(who, "reviews", "decide", team=team) == "all"
    with pytest.raises(Forbidden) as e:
        can(who, "agents", "edit", team=team)
    assert e.value.code == "role_required"
