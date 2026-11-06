"""Roles and what a person may do, by failure mode: two roles in one team showing only one role's actions, an
expired assignment still granting, a role change through the member routes leaving the old role's actions in place or
the token's permission version unchanged, and another person's permissions readable without a shared team."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
import sqlalchemy as sa

from ops_access import ACTIONS, AREAS, BUILTIN_ROLES, can
from ops_identity import Identity, http_current_version, mint_service_token
from ops_platform.store.roles import mirror_membership
from ops_platform.store.tables import members, role_assignments, teams, tenants
from ops_service_kit.errors import Forbidden, Unauthorized
from ops_service_kit.ids import new_id, now_iso

from .conftest import CALLER, Person, Platform


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
    # Admins hold every cell; settings.manage is still checked in the Security team.
    assert admin["grid"][AREAS.index("settings")]["actions"]["manage"] == "all"
    assert (await platform.public.get("/v1/roles/nope", headers=h)).status_code == 404


async def test_two_roles_in_one_team_add_up(platform: Platform) -> None:
    p = await platform.person(roles=("viewer",))
    team = next(iter(p.teams))
    await grant(platform, p, team, "reviewer")
    mine = held(await permissions(platform, await bearer(platform, p)), team)
    assert mine["agents.decide"]["roles"] == [{"id": "reviewer", "name": "Reviewer", "via": "person"}]
    assert {r["id"] for r in mine["agents.view"]["roles"]} == {"viewer", "reviewer"}
    # Viewer closes only its own cases, Reviewer any case: the wider scope wins across the two.
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


SECURITY_CELLS = {"secrets_egress.manage", "secrets_egress.decide", "settings.view", "settings.manage"}


async def test_a_security_team_action_is_listed_only_in_the_security_team(platform: Platform) -> None:
    """A builder's grid holds every cell of their team, egress included, but a service decides those cells in the
    Security team only. Listed under the builder's own team, the console offered him edits every service refuses."""
    p = await platform.person(roles=("builder",))
    team = next(iter(p.teams))
    mine = held(await permissions(platform, await bearer(platform, p)), team)
    assert "agents.create" in mine
    assert not SECURITY_CELLS & set(mine), sorted(SECURITY_CELLS & set(mine))
    async with platform.engine.begin() as c:
        await c.execute(
            teams.insert().values(
                id="team_security", tenant_id=p.tenant_id, name="Security", owner_groups=[], scope="owned",
                created_at=now_iso(),
            )
        )  # fmt: skip
    await join(platform, p, "team_security", "admin")
    security = held(await permissions(platform, await bearer(platform, p)), "team_security")
    assert security["secrets_egress.manage"]["securityTeamOnly"] is True
    # A workspace that names no Security team: nobody holds them, in any team.
    async with platform.engine.begin() as c:
        await c.execute(tenants.update().where(tenants.c.id == p.tenant_id).values(security_team_id=None))
    view = await permissions(platform, await bearer(platform, p))
    assert not any(SECURITY_CELLS & set(held(view, t["teamId"])) for t in view["teams"])


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


async def _principal(platform: Platform, h: dict[str, str], team: str, *, live: bool = False) -> Any:
    """`live`: the service asks platform's internal app for the tenant's permission version, as a deployed one does."""

    async def jwks() -> dict[str, Any]:
        return {"keys": [platform.signer.public_jwk()]}

    async def no_keys(_key: str) -> dict[str, Any] | None:
        return None

    def service_token(tenant: str) -> str:
        return mint_service_token(CALLER, service="agents", audience="platform", tenant_id=tenant)

    current = http_current_version(platform.internal, "http://platform-internal", service_token) if live else None
    identity = Identity(audience="agents", jwks=jwks, introspect=no_keys, current_version=current, version_cache_s=0)
    return await identity.principal(_Post(), authorization=h["Authorization"], x_team_id=team)  # pyright: ignore[reportArgumentType]


async def test_an_edit_to_a_built_in_role_reaches_every_services_decision_and_reset_undoes_it(
    platform: Platform,
) -> None:
    """The real seam: a workspace admin edits Viewer's cells; the viewer's next token carries them and a service's
    `can` decides from them; Reset to default puts the seed grid back. Each change is audited."""
    viewer = await platform.person(roles=("viewer",))
    team = next(iter(viewer.teams))
    owner = await platform.person(roles=("admin",), tenant_id=viewer.tenant_id)
    await grant(platform, owner, "*", "admin")
    ah = await bearer(platform, owner)
    seed = next(r for r in BUILTIN_ROLES if r.id == "viewer").grants
    cells = [{"area": a, "action": x, "scope": s} for a, x, s in seed] + [
        {"area": "agents", "action": "publish", "scope": "all"}
    ]
    before = claims(await bearer(platform, viewer))
    r = await platform.public.put("/v1/roles/viewer/permissions", headers=ah, json={"permissions": cells})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["grid"][AREAS.index("agents")]["actions"]["publish"] == "all"
    assert (await platform.public.get("/v1/roles/viewer", headers=ah)).json()["data"]["canEdit"] is True
    assert (await platform.public.get("/v1/roles/admin", headers=ah)).json()["data"]["canEdit"] is False
    vh0 = await bearer(platform, viewer)
    assert (await platform.public.get("/v1/roles/viewer", headers=vh0)).json()["data"]["canEdit"] is False
    vh = await bearer(platform, viewer)
    assert claims(vh)["perm_version"] > before["perm_version"]
    who = await _principal(platform, vh, team)
    assert can(who, "agents", "publish", team=team) == "all"
    r = await platform.public.post("/v1/roles/viewer/reset", headers=ah)
    assert r.status_code == 200, r.text
    who = await _principal(platform, await bearer(platform, viewer), team)
    with pytest.raises(Forbidden):
        can(who, "agents", "publish", team=team)
    audit = (await platform.public.get("/v1/audit", headers={**ah, "X-Team-Id": team})).json()["data"]["data"]
    assert {"role.edit", "role.reset"} <= {e.get("platformAction") or e.get("action") for e in audit}, audit[:3]


async def test_only_a_workspace_admin_edits_a_role_and_admin_keeps_every_cell(platform: Platform) -> None:
    team_admin = await platform.person(roles=("admin",))
    th = await bearer(platform, team_admin)
    cells = [{"area": "agents", "action": "view", "scope": "all"}]
    refused = await platform.public.put("/v1/roles/viewer/permissions", headers=th, json={"permissions": cells})
    assert refused.status_code == 403, refused.text
    await grant(platform, team_admin, "*", "admin")
    th = await bearer(platform, team_admin)
    kept = await platform.public.put("/v1/roles/admin/permissions", headers=th, json={"permissions": cells})
    assert kept.status_code == 409 and kept.json()["error"]["code"] == "admin_holds_every_cell", kept.text
    bad = [{"area": "agents", "action": "fly", "scope": "all"}]
    unknown = await platform.public.put("/v1/roles/viewer/permissions", headers=th, json={"permissions": bad})
    assert unknown.status_code in (400, 422), unknown.text


async def test_a_token_from_before_a_role_edit_is_refused_by_a_service_on_its_next_request(platform: Platform) -> None:
    """The real seam: a service resolving a token asks platform for the tenant's permission version, so a role edit
    applies on the next request instead of at the token's expiry; the refreshed token carries the edited cell."""
    viewer = await platform.person(roles=("viewer",))
    team = next(iter(viewer.teams))
    owner = await platform.person(roles=("admin",), tenant_id=viewer.tenant_id)
    await grant(platform, owner, "*", "admin")
    ah = await bearer(platform, owner)
    old = await bearer(platform, viewer)
    assert (await _principal(platform, old, team, live=True)).sub == viewer.user_id
    seed = next(r for r in BUILTIN_ROLES if r.id == "viewer").grants
    cells = [{"area": a, "action": x, "scope": s} for a, x, s in seed] + [
        {"area": "agents", "action": "publish", "scope": "all"}
    ]
    r = await platform.public.put("/v1/roles/viewer/permissions", headers=ah, json={"permissions": cells})
    assert r.status_code == 200, r.text
    with pytest.raises(Unauthorized) as refused:
        await _principal(platform, old, team, live=True)
    assert refused.value.code == "permissions_changed"
    who = await _principal(platform, await bearer(platform, viewer), team, live=True)
    assert can(who, "agents", "publish", team=team) == "all"


async def test_a_services_refusal_names_who_holds_the_cell_after_an_edit(platform: Platform) -> None:
    """The real seam: an admin unticks Builder's secrets_egress.create; a viewer's next token carries every built-in
    role's cells as the workspace holds them, so a service's refusal no longer names Builder."""
    viewer = await platform.person(roles=("viewer",))
    team = next(iter(viewer.teams))
    owner = await platform.person(roles=("admin",), tenant_id=viewer.tenant_id)
    await grant(platform, owner, "*", "admin")
    ah = await bearer(platform, owner)
    seed = next(r for r in BUILTIN_ROLES if r.id == "builder").grants
    cells = [{"area": a, "action": x, "scope": s} for a, x, s in seed if (a, x) != ("secrets_egress", "create")]
    r = await platform.public.put("/v1/roles/builder/permissions", headers=ah, json={"permissions": cells})
    assert r.status_code == 200, r.text
    who = await _principal(platform, await bearer(platform, viewer), team)
    with pytest.raises(Forbidden) as refused:
        can(who, "secrets_egress", "create", team=team)
    assert "Builder" not in refused.value.message, refused.value.message
