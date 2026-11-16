"""`/v1/me` reads its answer in its own few statements; `/v1/me/permissions` and `/v1/teams` read theirs through
`holdings_in` and `teams_of`. By failure mode: an assignment in an archived team counted, a team only an assignment
names left out or unnamed, a team-subject assignment missed, a `*` role missed, or a workspace admin's other teams
missing or given another role. Each answer must equal the other routes' for a person holding all of these."""

from __future__ import annotations

from typing import Any

from ops_access import ANY_TEAM
from ops_platform.store.tables import role_assignments, teams
from ops_service_kit.ids import new_id, now_iso

from .conftest import Person, Platform
from .test_members import bearer


async def _team(platform: Platform, tenant: str, status: str = "active") -> str:
    team = new_id("team")
    async with platform.engine.begin() as c:
        await c.execute(
            teams.insert().values(
                id=team, tenant_id=tenant, name=f"T {team}", owner_groups=[], scope="owned", status=status,
                created_at=now_iso(),
            )
        )  # fmt: skip
    return team


async def _assign(
    platform: Platform, p: Person, role: str, team: str, *, subject: tuple[str, str] | None = None
) -> None:
    kind, subject_id = subject or ("person", p.user_id)
    async with platform.engine.begin() as c:
        await c.execute(
            role_assignments.insert().values(
                id=new_id("ras"), tenant_id=p.tenant_id, subject_kind=kind, subject_id=subject_id, role_id=role,
                team_id=team, granted_by="test", reason="test", source="grant", created_at=now_iso(),
            )
        )  # fmt: skip


async def _same_answers(platform: Platform, p: Person) -> dict[str, Any]:
    h = await bearer(platform, p)
    me = (await platform.public.get("/v1/me", headers=h)).json()["data"]
    permissions = (await platform.public.get("/v1/me/permissions", headers=h)).json()["data"]
    listed = (await platform.public.get("/v1/teams", headers=h)).json()["data"]

    # Teams in the permissions come in no stated order from `holdings_in` (its read has no ORDER BY); /v1/me lists
    # them in membership order, so the two are compared team by team.
    def by_team(answer: dict[str, Any]) -> dict[str, Any]:
        return {**answer, "teams": sorted(answer["teams"], key=lambda t: t["teamId"])}

    assert by_team(me["permissions"]) == by_team(permissions)
    assert me["teams"] == [{"id": t["id"], "name": t["name"], "role": t["role"]} for t in listed]
    return me


async def test_me_answers_as_the_permissions_and_teams_routes_do(platform: Platform) -> None:
    admin = await platform.person(roles=("admin", "viewer"))
    tenant = admin.tenant_id
    member_viewer = next(t for t, r in admin.teams.items() if r == "viewer")
    archived = await _team(platform, tenant, status="archived")
    named_only, also_named, untouched = [await _team(platform, tenant) for _ in range(3)]
    await _assign(platform, admin, "reviewer", archived)
    await _assign(platform, admin, "builder", named_only)
    await _assign(platform, admin, "viewer", also_named)
    await _assign(platform, admin, "reviewer", member_viewer, subject=("team", member_viewer))
    await _assign(platform, admin, "admin", ANY_TEAM)
    me = await _same_answers(platform, admin)
    # The workspace admin sees every active team, the untouched one as admin, and nothing of the archived one.
    assert {t["id"]: t["role"] for t in me["teams"]}[untouched] == "admin"
    assert archived not in {t["id"] for t in me["teams"]}
    assert archived not in {t["teamId"] for t in me["permissions"]["teams"]}
    assert {named_only, also_named} <= {t["teamId"] for t in me["permissions"]["teams"]}

    builder = await platform.person(roles=("builder",), tenant_id=tenant)
    await _assign(platform, builder, "viewer", named_only)
    me = await _same_answers(platform, builder)
    assert [t["id"] for t in me["teams"]] == list(builder.teams)
