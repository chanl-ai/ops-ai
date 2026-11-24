"""Custom roles, by failure mode: someone other than a workspace admin makes or changes one; a copy carries secrets,
egress or Security-team cells, which only built-in roles give (D40); two roles share a name; a built-in role is renamed
or deleted; a role is deleted from under the people who hold it, or their move to another role is lost; a custom
role's cells never reach a service's decision; a change goes unaudited."""

from __future__ import annotations

from typing import Any

import pytest

from ops_access import BUILTIN_ROLES, can
from ops_platform.store.groups import GroupStore
from ops_platform.store.roles import RoleStore
from ops_service_kit.errors import Forbidden

from .conftest import Platform
from .test_holders import ask
from .test_permissions import _principal, bearer, claims, grant  # pyright: ignore[reportPrivateUsage]

# Cells a viewer does not hold, so a test sees what the custom role adds.
CASE_DESK = [
    {"area": "knowledge", "action": "create", "scope": "all"},
    {"area": "knowledge", "action": "edit", "scope": "all"},
]


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
    assert can(who, "knowledge", "edit", team=team) == "all"
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
    assert "secrets_egress.view" in data["leftOut"] and len(kept) == len(builder.grants) - len(data["leftOut"])
    given = [*CASE_DESK, {"area": "settings", "action": "manage", "scope": "all"}]
    r = await platform.public.post("/v1/roles", headers=ah, json={"name": "Too wide", "permissions": given})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "not_for_custom_roles"), r.text
    cells = [*data["permissions"], {"area": "secrets_egress", "action": "view", "scope": "all"}]
    r = await platform.public.put(f"/v1/roles/{data['id']}/permissions", headers=ah, json={"permissions": cells})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "not_for_custom_roles"), r.text


async def test_only_owner_holds_workspace_manage_on_a_custom_or_edited_built_in_role(platform: Platform) -> None:
    """E42: `workspace.manage` transfers and closes the workspace, held by Owner alone; a custom role made with it, or
    a built-in role edited to hold it, is refused."""
    _, ah = await _admin(platform)
    owns = {"area": "workspace", "action": "manage", "scope": "all"}
    made = await platform.public.post("/v1/roles", headers=ah, json={"name": "Closer", "permissions": [owns]})
    assert (made.status_code, made.json()["error"]["code"]) == (400, "not_for_custom_roles"), made.text
    builder = next(r for r in BUILTIN_ROLES if r.id == "builder")
    cells = [{"area": a, "action": x, "scope": s} for a, x, s in builder.grants] + [owns]
    edited = await platform.public.put("/v1/roles/builder/permissions", headers=ah, json={"permissions": cells})
    assert (edited.status_code, edited.json()["error"]["code"]) == (400, "owner_only"), edited.text


async def test_a_workspace_admin_cannot_edit_owner_or_security_admin_with_one_cell_or_none(platform: Platform) -> None:
    """Owner and Security admin come by rule; an edit that narrowed Owner locked the workspace out of a transfer, and
    an empty list left it read as the seed by one check and as nothing by another."""
    _, ah = await _admin(platform)
    one = [{"area": "knowledge", "action": "view", "scope": "all"}]
    for role in ("owner", "security_admin"):
        for cells in (one, []):
            r = await platform.public.put(f"/v1/roles/{role}/permissions", headers=ah, json={"permissions": cells})
            assert (r.status_code, r.json()["error"]["code"]) == (409, "role_set_by_rule"), (role, cells, r.text)
        read = await platform.public.get(f"/v1/roles/{role}", headers=ah)
        assert read.json()["data"]["canEdit"] is False, read.text


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
    holders = (await platform.public.get(f"/v1/roles/{rid}/holders", headers=ah)).json()["data"]["data"]
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


async def test_an_admin_gives_and_takes_a_custom_role_in_the_team_they_act_in(platform: Platform) -> None:
    owner, ah = await _admin(platform)
    rid = (
        await platform.public.post("/v1/roles", headers=ah, json={"name": "Desk 2", "permissions": CASE_DESK})
    ).json()["data"]["id"]
    member = await platform.person(roles=("viewer",), tenant_id=owner.tenant_id)
    team = next(iter(member.teams))
    path = f"/v1/people/{member.user_id}/role-grants"
    # A workspace admin acts in every team, the member's made after their sign-in included once they sign in again.
    th = {**await bearer(platform, owner), "X-Team-Id": team}
    mh = {**await bearer(platform, member), "X-Team-Id": team}
    refused = await platform.public.post(path, headers=mh, json={"roleId": rid})
    assert refused.status_code == 403, refused.text
    given = await platform.public.post(path, headers=th, json={"roleId": rid})
    assert given.status_code == 201 and given.json()["data"]["roleName"] == "Desk 2", given.text
    again = await platform.public.post(path, headers=th, json={"roleId": rid})
    assert again.json()["error"]["code"] == "already_granted", again.text
    builtin = await platform.public.post(path, headers=th, json={"roleId": "builder"})
    assert builtin.json()["error"]["code"] == "builtin_role", builtin.text
    outside = await platform.public.post(
        path, headers={**ah, "X-Team-Id": next(iter(owner.teams))}, json={"roleId": rid}
    )
    assert outside.json()["error"]["code"] == "not_a_member", outside.text
    who = await _principal(platform, await bearer(platform, member), team)
    assert can(who, "knowledge", "edit", team=team) == "all"
    listed = (await platform.public.get(path, headers=th)).json()["data"]["data"]
    taken = await platform.public.delete(f"{path}/{listed[0]['id']}", headers=th)
    assert taken.status_code == 204, taken.text
    who = await _principal(platform, await bearer(platform, member), team)
    with pytest.raises(Forbidden):
        can(who, "knowledge", "edit", team=team)


async def test_a_role_page_gives_a_role_to_a_group_from_one_picker_and_the_member_holds_it(platform: Platform) -> None:
    owner, ah = await _admin(platform)
    rid = (
        await platform.public.post("/v1/roles", headers=ah, json={"name": "Desk 3", "permissions": CASE_DESK})
    ).json()["data"]["id"]
    member = await platform.person(roles=("viewer",), tenant_id=owner.tenant_id)
    team = next(iter(member.teams))
    th = {**await bearer(platform, owner), "X-Team-Id": team}
    groups = GroupStore(platform.store)
    desk = await groups.create(owner.tenant_id, name="Case desk", by=owner.user_id, request_id="r")
    await groups.add_member(owner.tenant_id, desk, member.user_id, by=owner.user_id, request_id="r")
    offered = await platform.public.get(f"/v1/roles/{rid}/holder-options", headers=th, params={"search": "case"})
    assert offered.status_code == 200, offered.text
    assert [o["id"] for o in offered.json()["data"]["data"]] == [f"group:{desk}"], offered.text
    people = await platform.public.get(f"/v1/roles/{rid}/holder-options", headers=th)
    assert f"person:{member.user_id}" in {o["id"] for o in people.json()["data"]["data"]}, people.text
    given = await platform.public.post(f"/v1/roles/{rid}/holders", headers=th, json={"kind": "group", "id": desk})
    assert given.status_code == 201, given.text
    assert given.json()["data"] == {"kind": "group", "id": desk, "teamId": team, "name": "Case desk", "email": None}
    who = await _principal(platform, await bearer(platform, member), team)
    assert can(who, "knowledge", "edit", team=team) == "all"
    audit = (await platform.public.get("/v1/audit", headers=th)).json()["data"]["data"]
    assert any((e.get("platformAction") or e.get("action")) == "role.grant" for e in audit), audit[:4]


async def test_giving_a_role_from_its_page_refuses_a_non_admin_an_unknown_group_and_a_privileged_role(
    platform: Platform,
) -> None:
    owner, ah = await _admin(platform)
    member = await platform.person(roles=("viewer",), tenant_id=owner.tenant_id)
    team = next(iter(member.teams))
    th = {**await bearer(platform, owner), "X-Team-Id": team}
    mh = {**await bearer(platform, member), "X-Team-Id": team}
    plain = (
        await platform.public.post("/v1/roles", headers=ah, json={"name": "Desk 4", "permissions": CASE_DESK})
    ).json()["data"]["id"]
    keys = [{"area": "access", "action": "edit", "scope": "all"}]
    strong = (await platform.public.post("/v1/roles", headers=ah, json={"name": "Desk 5", "permissions": keys})).json()
    group = await GroupStore(platform.store).create(owner.tenant_id, name="Leads", by=owner.user_id, request_id="r")
    asked = {"kind": "person", "id": member.user_id}
    refused = await platform.public.post(f"/v1/roles/{plain}/holders", headers=mh, json=asked)
    assert refused.status_code == 403, refused.text
    unknown = await platform.public.post(
        f"/v1/roles/{plain}/holders", headers=th, json={"kind": "group", "id": "grp_x"}
    )
    assert unknown.status_code == 404, unknown.text
    held = await platform.public.post(
        f"/v1/roles/{strong['data']['id']}/holders", headers=th, json={"kind": "group", "id": group}
    )
    assert held.json()["error"]["code"] == "privileged_for_group", held.text


async def test_role_lists_never_show_another_persons_or_tenants_rows(platform: Platform) -> None:
    # A person's grants are theirs only; a role's holders are that role's, in this tenant only; the roles are this
    # tenant's; `ids` and a search naming the others each still answer the asked-for rows only.
    made: dict[str, list[str]] = {}
    people: dict[str, Any] = {}
    for tenant in ("mine", "outside"):
        owner, ah = await _admin(platform)
        rid = await platform.public.post("/v1/roles", headers=ah, json={"name": "Desk", "permissions": CASE_DESK})
        for who in ("a", "b"):
            member = await platform.person(roles=("viewer",), tenant_id=owner.tenant_id)
            th = {**await bearer(platform, owner), "X-Team-Id": next(iter(member.teams))}
            path = f"/v1/people/{member.user_id}/role-grants"
            given = await platform.public.post(path, headers=th, json={"roleId": rid.json()["data"]["id"]})
            assert given.status_code == 201, given.text
            made.setdefault(tenant + who, []).append(given.json()["data"]["id"])
            people[tenant + who] = member
        people[tenant] = (owner, ah)
        made[tenant] = [rid.json()["data"]["id"]]
    owner, ah = people["mine"]
    mine, theirs = made["minea"], {*made["mineb"], *made["outsidea"], *made["outsideb"]}
    path = f"/v1/people/{people['minea'].user_id}/role-grants"
    for params in ({}, {"search": "desk"}, {"ids": [*mine, *theirs]}):
        r = await platform.public.get(path, headers=ah, params=params)
        assert r.status_code == 200, r.text
        listed = {g["id"] for g in r.json()["data"]["data"]}
        assert listed == set(mine), (params, listed)
    outsiders = {people["outsidea"].user_id, people["outsideb"].user_id, people["outside"][0].user_id}
    # A holder's `id` is the person's or team's, so `ids` names people and teams too.
    asked = [people["minea"].user_id, owner.user_id, *outsiders]
    for params in ({}, {"search": "@"}, {"pageSize": 50}, {"ids": asked}):
        r = await platform.public.get("/v1/roles/viewer/holders", headers=ah, params=params)
        assert r.status_code == 200, r.text
        held = {h["id"] for h in r.json()["data"]["data"]}
        assert people["minea"].user_id in held and owner.user_id not in held and not held & outsiders, (params, held)
    for params in ({}, {"search": "desk"}, {"ids": [*made["mine"], *made["outside"]]}):
        r = await platform.public.get("/v1/roles", headers=ah, params=params)
        assert r.status_code == 200, r.text
        listed = {x["id"] for x in r.json()["data"]["data"]}
        assert made["mine"][0] in listed and made["outside"][0] not in listed, (params, listed)


async def test_the_roles_list_keeps_built_in_or_custom_roles_and_those_that_decide_reviews(platform: Platform) -> None:
    _, ah = await _admin(platform)
    decides = [{"area": "reviews", "action": "decide", "scope": "own"}]
    for name, cells in (("Case desk", CASE_DESK), ("Review desk", decides)):
        made = await platform.public.post("/v1/roles", headers=ah, json={"name": name, "permissions": cells})
        assert made.status_code == 201, made.text
    # Another tenant's deciding role never reaches this tenant's list, whatever the filter.
    _, other = await _admin(platform)
    await platform.public.post("/v1/roles", headers=other, json={"name": "Elsewhere", "permissions": decides})
    builtin = {r.name for r in BUILTIN_ROLES}
    deciding = {r.name for r in BUILTIN_ROLES if any(g[:2] == ("reviews", "decide") for g in r.grants)}
    for params, expected in (
        ({}, builtin | {"Case desk", "Review desk"}),
        ({"builtin": "true"}, builtin),
        ({"builtin": "false"}, {"Case desk", "Review desk"}),
        ({"canDecideReviews": "true"}, deciding | {"Review desk"}),
        ({"canDecideReviews": "false"}, (builtin - deciding) | {"Case desk"}),
        ({"builtin": "false", "canDecideReviews": "true"}, {"Review desk"}),
    ):
        r = await platform.public.get("/v1/roles", headers=ah, params={**params, "pageSize": 100})
        assert r.status_code == 200, r.text
        names = [row["name"] for row in r.json()["data"]["data"]]
        assert set(names) == expected and r.json()["data"]["pagination"]["total"] == len(expected), (params, names)
    assert (await platform.public.get("/v1/roles", headers=ah, params={"builtin": "yes"})).status_code == 400


async def test_the_roles_list_the_holders_and_the_live_check_read_a_built_in_role_alike(platform: Platform) -> None:
    """An admin who cleared an editable built-in role removed nothing (it read as its seed), yet the roles list counted
    no cells and the holders named nobody through it. An empty list is refused; a role with no rows reads as its seed
    on every reader, and a narrowed one as what it holds."""
    owner, ah = await _admin(platform)
    tenant = owner.tenant_id
    ben = await platform.person(roles=("builder",), tenant_id=tenant)
    team = next(iter(ben.teams))
    r = await platform.public.put("/v1/roles/builder/permissions", headers=ah, json={"permissions": []})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "builtin_role_empty"), r.text
    store = RoleStore(platform.store)
    seed = {r.id: r for r in BUILTIN_ROLES}

    async def readers(cell: tuple[str, str]) -> tuple[dict[str, int], set[str], list[str], bool]:
        listed = await platform.public.get("/v1/roles", headers=ah, params={"pageSize": 100})
        counts = {x["id"]: x["permissionCount"] for x in listed.json()["data"]["data"]}
        q = {"pageSize": 100, "canDecideReviews": "true"}
        deciding = await platform.public.get("/v1/roles", headers=ah, params=q)
        decides = {x["id"] for x in deciding.json()["data"]["data"]}
        status, body = await ask(platform, owner, team, *cell)
        assert status == 200, body
        held = [h["id"] for h in body["data"]["holders"]]
        who, access = await store.live(tenant, ben.user_id, team=team)
        try:
            access.can(who, *cell, team=team)
            live = True
        except Forbidden:
            live = False
        return counts, decides, held, live

    # No rows, as a workspace made before the seed held them: every reader answers the seed.
    await store.set_grid(tenant, "builder", [], by="usr_admin", request_id="r", action="role.edit")
    counts, decides, held, live = await readers(("agents", "edit"))
    assert counts["builder"] == len(seed["builder"].grants), counts
    assert "builder" in decides and ben.user_id in held and live, (decides, held, live)
    # Narrowed to one cell: every reader answers that cell alone.
    one = [{"area": "knowledge", "action": "view", "scope": "all"}]
    r = await platform.public.put("/v1/roles/builder/permissions", headers=ah, json={"permissions": one})
    assert r.status_code == 200, r.text
    counts, decides, held, live = await readers(("agents", "edit"))
    assert counts["builder"] == 1 and "builder" not in decides and ben.user_id not in held and not live
    _, _, held, live = await readers(("knowledge", "view"))
    assert ben.user_id in held and live, held


async def test_a_copy_of_admin_leaves_approve_own_requests_out(platform: Platform) -> None:
    """Approvals · decide is "approve own requests"; a copy never carries it, so a role gains it only by a tick."""
    _, ah = await _admin(platform)
    copied = await platform.public.post("/v1/roles", headers=ah, json={"name": "Admin too", "copyOf": "admin"})
    assert copied.status_code == 201, copied.text
    data = copied.json()["data"]
    assert ("approvals", "decide") not in {(p["area"], p["action"]) for p in data["permissions"]}
    assert "approvals.decide" in data["leftOut"]
