"""Roles given to groups, by failure mode, decided by `can()` on the token a sign-in mints: a group's role in one team
granting something in another; a group's role in every team missing a team made after it; a group carrying a
privileged cell, given so or gained later; taking one group's role away taking more than it gave; and the groups
tables reading back otherwise on SQL Server. Runs on both databases (BOTH_DATABASES)."""

from __future__ import annotations

from typing import Any

import pytest

from ops_access import ANY_TEAM, Grant, can
from ops_platform.store.groups import GroupStore
from ops_platform.store.roles import PrivilegedForGroupError, RoleStore
from ops_platform.store.tables import teams
from ops_service_kit.errors import Forbidden
from ops_service_kit.ids import new_id, now_iso

from .conftest import Person, Platform, seed_tx
from .test_permissions import _principal, bearer  # pyright: ignore[reportPrivateUsage]

BY = "usr_admin"


async def _may(platform: Platform, p: Person, team: str, area: str, action: str) -> bool:
    """Whether `can()` lets the person act on a record of `team`, from the token a sign-in mints now, acting in their
    first team (a team they are not a member of is not in the token's `team_ids`)."""
    who = await _principal(platform, await bearer(platform, p), next(iter(p.teams)))
    try:
        can(who, area, action, team=team, from_any_team=True)
    except Forbidden:
        return False
    return True


async def _group(platform: Platform, p: Person, *members: Person) -> str:
    groups = GroupStore(platform.store)
    group = await groups.create(p.tenant_id, name=f"Group {new_id('g')}", by=BY, request_id=new_id("req"))
    for m in members:
        assert await groups.add_member(p.tenant_id, group, m.user_id, by=BY, request_id=new_id("req"))
    return group


async def _give(platform: Platform, p: Person, group: str, role: str, team: str) -> str:
    return await RoleStore(platform.store).assign(
        p.tenant_id, subject_kind="group", subject_id=group, role_id=role, team_id=team, by=BY, request_id=new_id("r")
    )


async def _custom(platform: Platform, p: Person, cells: list[Any]) -> str:
    return await RoleStore(platform.store).create(
        p.tenant_id, name=f"Role {new_id('n')}", description="", grants=cells, by=BY, request_id=new_id("req")
    )


async def test_a_groups_role_in_one_team_grants_nothing_in_another(platform: Platform) -> None:
    ana = await platform.person(roles=("chat_user", "chat_user"))
    team_a, team_b = list(ana.teams)
    await _give(platform, ana, await _group(platform, ana, ana), "builder", team_a)
    assert await _may(platform, ana, team_a, "agents", "edit")
    assert not await _may(platform, ana, team_b, "agents", "edit")


async def test_a_groups_role_in_every_team_applies_in_a_team_made_after_it(platform: Platform) -> None:
    ana = await platform.person(roles=("chat_user",))
    await _give(platform, ana, await _group(platform, ana, ana), "builder", ANY_TEAM)
    later = new_id("team")
    async with seed_tx(platform.engine, ana.tenant_id) as c:
        await c.execute(
            teams.insert().values(
                id=later, tenant_id=ana.tenant_id, name=f"Later {later}", owner_groups=[], scope="owned",
                created_at=now_iso(),
            )
        )  # fmt: skip
    assert await _may(platform, ana, later, "agents", "edit")


async def test_a_group_never_carries_a_privileged_cell(platform: Platform) -> None:
    ana = await platform.person(roles=("chat_user",))
    team = next(iter(ana.teams))
    group = await _group(platform, ana, ana)
    with pytest.raises(PrivilegedForGroupError) as refused:
        await _give(platform, ana, group, "admin", team)
    assert "access.manage" in refused.value.cells
    # Reviewer decides a module's security review only in the Security team, so a group gives it elsewhere only.
    await _give(platform, ana, group, "reviewer", team)
    with pytest.raises(PrivilegedForGroupError):
        await _give(platform, ana, group, "reviewer", "team_security")
    # A role that gains a privileged cell after a group was given it counts for nothing through the group.
    lead = await _custom(platform, ana, [("knowledge", "edit", "all")])
    await _give(platform, ana, group, lead, team)
    assert await _may(platform, ana, team, "knowledge", "edit")
    widened: list[Grant] = [("knowledge", "edit", "all"), ("access", "manage", "all")]
    await RoleStore(platform.store).set_grid(ana.tenant_id, lead, widened, by=BY, request_id="r", action="role.edit")
    assert not await _may(platform, ana, team, "access", "manage")
    assert not await _may(platform, ana, team, "knowledge", "edit")


async def test_an_emptied_owner_or_security_admin_is_still_refused_to_a_group(platform: Platform) -> None:
    """A built-in role with no stored cells answers its seed to the live check, so the group guard must too: emptied
    rows never let Owner or Security admin reach a group."""
    ana = await platform.person(roles=("chat_user",))
    group = await _group(platform, ana, ana)
    store = RoleStore(platform.store)
    for role in ("owner", "security_admin"):
        await store.set_grid(ana.tenant_id, role, [], by=BY, request_id="r", action="role.edit")
        with pytest.raises(PrivilegedForGroupError):
            await _give(platform, ana, group, role, ANY_TEAM)


async def test_taking_a_groups_role_away_takes_back_only_what_it_gave(platform: Platform) -> None:
    ana = await platform.person(roles=("chat_user",))
    ben = await platform.person(roles=("chat_user",), tenant_id=ana.tenant_id)
    team = next(iter(ana.teams))
    reviewers, leads = await _group(platform, ana, ana), await _group(platform, ana, ana, ben)
    given = await _give(platform, ana, reviewers, "reviewer", team)
    await _give(platform, ana, leads, await _custom(platform, ana, [("knowledge", "edit", "all")]), team)
    assert await RoleStore(platform.store).ungrant(ana.tenant_id, given, by=BY, request_id="r")
    assert not await _may(platform, ana, team, "reviews", "decide")
    assert await _may(platform, ana, team, "knowledge", "edit")
    assert await GroupStore(platform.store).remove_member(ana.tenant_id, leads, ana.user_id, by=BY, request_id="r")
    assert not await _may(platform, ana, team, "knowledge", "edit")
    assert await _may(platform, ben, team, "knowledge", "edit")
    # Her own team role stays through both.
    assert await _may(platform, ana, team, "chat", "run")


async def test_groups_and_their_roles_read_back_the_same_on_each_database(platform: Platform) -> None:
    ana = await platform.person(roles=("viewer",))
    team = next(iter(ana.teams))
    group = await _group(platform, ana, ana)
    until = "2999-01-01T00:00:00.000Z"
    await RoleStore(platform.store).assign(
        ana.tenant_id, subject_kind="group", subject_id=group, role_id="builder", team_id=ANY_TEAM, by=BY,
        request_id="r", expires_at=until,
    )  # fmt: skip
    held = await RoleStore(platform.store).holdings(ana.tenant_id, ana.user_id)
    rows = sorted((a.role_id, a.team_id, a.via, a.expires_at) for a in held.assignments)
    assert rows == [("builder", ANY_TEAM, "group", until), ("viewer", team, "person", None)], rows
    assert await GroupStore(platform.store).delete(ana.tenant_id, group, by=BY, request_id="r")
    held = await RoleStore(platform.store).holdings(ana.tenant_id, ana.user_id)
    assert [(a.role_id, a.via) for a in held.assignments] == [("viewer", "person")]
