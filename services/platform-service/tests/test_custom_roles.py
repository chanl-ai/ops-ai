"""Custom roles, by failure mode: someone other than a workspace admin makes or changes one; a copy carries secrets,
egress or Security-team cells, which only built-in roles give (D40); two roles share a name; a built-in role is renamed
or deleted; a role is deleted from under the people who hold it, or their move to another role is lost; a custom
role's cells never reach a service's decision; a change goes unaudited."""

from __future__ import annotations

from typing import Any

import pytest

from ops_access import BUILTIN_ROLES, can
from ops_service_kit.errors import Forbidden

from .conftest import Platform
from .test_permissions import _principal, bearer, claims, grant  # pyright: ignore[reportPrivateUsage]

CASE_DESK = [{"area": "cases", "action": "view", "scope": "all"}, {"area": "cases", "action": "edit", "scope": "all"}]


async def _admin(platform: Platform) -> tuple[Any, dict[str, str]]:
    owner = await platform.person(roles=("admin",))
    await grant(platform, owner, "*", "admin")
    return owner, await bearer(platform, owner)


async def test_a_workspace_admin_makes_a_role_whose_cells_decide_in_a_service(platform: Platform) -> None:
    owner, ah = await _admin(platform)
    made = await platform.public.post("/v1/roles", headers=ah, json={"name": "Case desk", "permissions": CASE_DESK})
    assert made.status_code == 201, made.text
    role = made.json()["data"]
    assert role["builtin"] is False and role["permissionCount"] == 2 and role["canEdit"] is True
    viewer = await platform.person(roles=("viewer",), tenant_id=owner.tenant_id)
    team = next(iter(viewer.teams))
    assert (
        await platform.public.post("/v1/roles", headers=await bearer(platform, viewer), json={"name": "x"})
    ).status_code == 403
    await grant(platform, viewer, team, role["id"])
    who = await _principal(platform, await bearer(platform, viewer), team)
    assert can(who, "cases", "edit", team=team) == "all"
    with pytest.raises(Forbidden):
        can(who, "agents", "edit", team=team)


async def test_a_custom_role_never_holds_secrets_egress_or_security_team_cells(platform: Platform) -> None:
    _, ah = await _admin(platform)
    copied = await platform.public.post("/v1/roles", headers=ah, json={"name": "Builder too", "copyOf": "builder"})
    assert copied.status_code == 201, copied.text
    data = copied.json()["data"]
    builder = next(r for r in BUILTIN_ROLES if r.id == "builder")
    kept = {(p["area"], p["action"]) for p in data["permissions"]}
    assert not any(a == "secrets_egress" for a, _ in kept)
    assert "secrets_egress.create" in data["leftOut"] and len(kept) == len(builder.grants) - len(data["leftOut"])
    given = [*CASE_DESK, {"area": "settings", "action": "manage", "scope": "all"}]
    r = await platform.public.post("/v1/roles", headers=ah, json={"name": "Too wide", "permissions": given})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "not_for_custom_roles"), r.text
    cells = [*data["permissions"], {"area": "secrets_egress", "action": "view", "scope": "all"}]
    r = await platform.public.put(f"/v1/roles/{data['id']}/permissions", headers=ah, json={"permissions": cells})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "not_for_custom_roles"), r.text


async def test_names_are_unique_and_built_in_roles_keep_theirs(platform: Platform) -> None:
    _, ah = await _admin(platform)
    first = (await platform.public.post("/v1/roles", headers=ah, json={"name": "Fraud desk"})).json()["data"]
    taken = await platform.public.post("/v1/roles", headers=ah, json={"name": "fraud DESK"})
    assert (taken.status_code, taken.json()["error"]["code"]) == (409, "name_taken"), taken.text
    renamed = await platform.public.patch(f"/v1/roles/{first['id']}", headers=ah, json={"name": "Fraud review"})
    assert renamed.status_code == 200 and renamed.json()["data"]["name"] == "Fraud review", renamed.text
    clash = await platform.public.patch(f"/v1/roles/{first['id']}", headers=ah, json={"name": "Builder"})
    assert clash.json()["error"]["code"] == "name_taken", clash.text
    for r in (
        await platform.public.patch("/v1/roles/builder", headers=ah, json={"name": "Makers"}),
        await platform.public.delete("/v1/roles/viewer", headers=ah),
    ):
        assert (r.status_code, r.json()["error"]["code"]) == (409, "builtin_role"), r.text


async def test_a_held_role_is_deleted_only_by_moving_its_holders_and_every_change_is_audited(
    platform: Platform,
) -> None:
    owner, ah = await _admin(platform)
    role = (await platform.public.post("/v1/roles", headers=ah, json={"name": "Desk", "permissions": CASE_DESK})).json()
    rid = role["data"]["id"]
    person = await platform.person(roles=("viewer",), tenant_id=owner.tenant_id)
    team = next(iter(person.teams))
    await grant(platform, person, team, rid)
    holders = (await platform.public.get(f"/v1/roles/{rid}/holders", headers=ah)).json()["data"]
    assert [(h["id"], h["teamId"]) for h in holders] == [(person.user_id, team)]
    held = await platform.public.delete(f"/v1/roles/{rid}", headers=ah)
    assert (held.status_code, held.json()["error"]["code"]) == (409, "role_in_use"), held.text
    assert held.json()["error"]["details"]["holders"][0]["id"] == person.user_id
    moved = await platform.public.delete(f"/v1/roles/{rid}", headers=ah, params={"moveTo": "builder"})
    assert moved.status_code == 204, moved.text
    assert "builder" in claims(await bearer(platform, person))["access"][team]
    assert (await platform.public.get(f"/v1/roles/{rid}", headers=ah)).status_code == 404
    mine = next(iter(owner.teams))
    audit = (await platform.public.get("/v1/audit", headers={**ah, "X-Team-Id": mine})).json()["data"]["data"]
    actions = {e.get("platformAction") or e.get("action") for e in audit}
    assert {"role.create", "role.delete"} <= actions, audit[:4]
