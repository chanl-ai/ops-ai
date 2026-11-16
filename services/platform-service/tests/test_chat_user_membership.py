"""Chat user given like any other membership role (E31), by failure mode: an invite or a role change refuses it (C1);
the person gets more or less than the Chat user cells afterwards (C2); the membership and its built-in assignment
disagree after a change to or from it (C3); the audit line names the raw stored value (C4); demoting the last admin
to it goes through (C5)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from ops_platform.store.tables import role_assignments, role_permissions, roles
from ops_service_kit.ids import new_id, now_iso

from .conftest import Platform
from .test_audit_route import audit
from .test_members import as_admin, bearer, invite_one, join, member_rows, team_of
from .test_permissions import grant, held, permissions


async def _assigned(platform: Platform, user_id: str, team: str) -> list[str]:
    async with platform.engine.connect() as c:
        q = sa.select(role_assignments.c.role_id).where(
            role_assignments.c.subject_id == user_id, role_assignments.c.team_id == team
        )
        return sorted(str(r) for r in (await c.execute(q)).scalars())


async def test_an_invited_chat_user_only_chats_and_the_invite_is_audited(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    team = team_of(admin)
    token = await invite_one(platform, h, "chatter@bank.test", role="chat_user")
    r = await platform.public.post(f"/v1/invites/{token}/accept", json={"name": "Chat Ter"})
    assert r.status_code == 200, r.text
    session = r.json()["data"]
    assert session["principal"]["roles"] == {team: "chat_user"}
    mine = {"Authorization": f"Bearer {session['token']}", "X-Team-Id": team}
    cells = held(await permissions(platform, mine), team)
    assert sorted(cells) == ["chat.run", "chat.view", "memory.edit"], sorted(cells)
    refused = await platform.public.get("/v1/settings/members", headers=mine)
    assert refused.status_code == 403, refused.text
    [invited] = (await audit(platform, h, kind="invited"))["data"]
    assert invited["summary"] == "Invited chatter@bank.test as chat user", invited["summary"]


async def test_a_role_change_to_and_from_chat_user_moves_the_assignment_and_is_audited(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    team = team_of(admin)
    viewer = await join(platform, admin, "viewer")
    [row] = await member_rows(platform, h, role="viewer")
    for role, builtin in (("chat_user", "chat_user"), ("viewer", "viewer")):
        r = await platform.public.post("/v1/settings/members/role", headers=h, json={"ids": [row["id"]], "role": role})
        assert r.status_code == 200 and r.json()["data"]["updated"] == [row["id"]], r.text
        assert [m["email"] for m in await member_rows(platform, h, role=role)] == [viewer.email]
        assert await _assigned(platform, viewer.user_id, team) == [builtin]
    summaries = [e["summary"] for e in (await audit(platform, h))["data"]]
    for change in ("role from viewer to chat user", "role from chat user to viewer"):
        assert any(s.startswith("Changed ") and s.endswith(change) for s in summaries), summaries


async def test_the_last_admin_is_not_demoted_to_chat_user(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    [me] = [m for m in await member_rows(platform, h) if m["email"] == admin.email]
    r = await platform.public.post(
        "/v1/settings/members/role", headers=h, json={"ids": [me["id"]], "role": "chat_user"}
    )
    assert r.json()["data"] == {"updated": [], "skipped": [{"id": me["id"], "reason": "last_admin"}]}, r.text


@pytest.mark.parametrize(
    "path",
    [
        "/v1/access/holders?area=agents&action=edit",
        "/v1/policies",
        "/v1/policies/requesterMayDecide",
        "/v1/people/{other}/role-grants",
        "/v1/people/{other}/permissions",
        "/v1/people-names",
        "/v1/team-names",
    ],
)
async def test_only_a_chat_user_is_refused_and_every_other_membership_still_reads(
    platform: Platform, path: str
) -> None:
    # On develop any member read these. A Chat user holds own-thread chat and own memory only, so who holds what, the
    # policies, another person's grants and the workspace's names answer 403 through can() on access.view, the cell
    # that reads a team's people. Every other membership role holds it and still reads them (Admin with Security
    # admin, as the Security team's admins hold it); a Chat user given a custom role with access.view reads them too.
    admin, _ = await as_admin(platform)
    team = team_of(admin)
    url = path.format(other=admin.user_id)
    reader = new_id("role")
    async with platform.engine.begin() as c:
        await c.execute(
            roles.insert().values(
                tenant_id=admin.tenant_id, id=reader, name="People reader", builtin=False, description="",
                created_at=now_iso(),
            )
        )  # fmt: skip
        await c.execute(
            role_permissions.insert().values(
                tenant_id=admin.tenant_id, role_id=reader, area="access", action="view", scope="all"
            )
        )  # fmt: skip
    for role, extra, status in (
        ("chat_user", None, 403),
        ("viewer", None, 200),
        ("builder", None, 200),
        ("approver", None, 200),
        ("admin", "security_admin", 200),
        ("chat_user", reader, 200),
    ):
        person = await join(platform, admin, role)
        if extra is not None:
            await grant(platform, person, team, extra)
        mine = {**await bearer(platform, person), "X-Team-Id": team}
        r = await platform.public.get(url, headers=mine)
        assert r.status_code == status, (role, extra, r.text)
        if status == 403:
            assert r.json()["error"]["code"] == "admin_required", r.text
            own = await platform.public.get(f"/v1/people/{person.user_id}/role-grants", headers=mine)
            assert own.status_code == 200, own.text
