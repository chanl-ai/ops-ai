"""Reading the audit log (P12, I7), by failure mode: a non-admin reads it, a team reads another team's entries, the
filters let rows through that do not match, and a write that fails part-way leaves entries behind."""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa

from ops_platform.store.audit import record
from ops_platform.store.tables import audit_entries, members, teams

from .conftest import Platform
from .test_members import as_admin, invite_one, join


async def audit(platform: Platform, h: dict[str, str], **params: Any) -> dict[str, Any]:
    r = await platform.public.get("/v1/audit", headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_an_admin_reads_their_teams_entries_with_actor_request_and_target(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    await invite_one(platform, h, "seen@bank.test")
    neighbour = await platform.person(roles=("admin",), tenant_id=admin.tenant_id)
    token = (await platform.sign_in(neighbour)).json()["data"]["token"]
    await invite_one(platform, {"Authorization": f"Bearer {token}"}, "unseen@bank.test")
    page = await audit(platform, h)
    [entry] = [e for e in page["data"] if e["action"] == "member.invite"]
    assert entry["actor"] == admin.user_id and entry["requestId"].startswith("req_")
    assert entry["targetKind"] == "member" and entry["detail"]["email"] == "seen@bank.test"
    assert all(e["teamId"] == h["X-Team-Id"] for e in page["data"])


async def test_only_an_admin_reads_the_audit(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    for role in ("viewer", "builder", "approver"):
        other = await join(platform, admin, role)
        token = (await platform.sign_in(other)).json()["data"]["token"]
        r = await platform.public.get(
            "/v1/audit", headers={"Authorization": f"Bearer {token}", "X-Team-Id": h["X-Team-Id"]}
        )
        assert r.status_code == 403, role


async def test_filters_and_pages(platform: Platform) -> None:
    _, h = await as_admin(platform)
    for n in range(3):
        await invite_one(platform, h, f"page{n}@bank.test")
    page = await audit(platform, h, action="member.invite", pageSize=2)
    assert len(page["data"]) == 2 and page["pagination"]["total"] == 3 and page["pagination"]["hasNext"]
    assert all(e["action"] == "member.invite" for e in page["data"])
    rest = await audit(platform, h, action="member.invite", pageSize=2, page=2)
    assert len(rest["data"]) == 1
    assert (await audit(platform, h, targetKind="api_key"))["data"] == []
    assert (await audit(platform, h, to="2000-01-01T00:00:00.000Z"))["data"] == []


async def test_a_platform_scope_team_reads_every_entry_in_the_tenant(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    async with platform.engine.begin() as c:
        await c.execute(teams.update().where(teams.c.id == h["X-Team-Id"]).values(scope="all"))
    neighbour = await platform.person(roles=("admin",), tenant_id=admin.tenant_id)
    token = (await platform.sign_in(neighbour)).json()["data"]["token"]
    await invite_one(platform, {"Authorization": f"Bearer {token}"}, "elsewhere@bank.test")
    actions = {(e["action"], e["teamId"]) for e in (await audit(platform, h))["data"]}
    assert ("member.invite", next(iter(neighbour.teams))) in actions
    assert ("auth.sign_in", None) in actions


async def test_a_write_that_fails_part_way_leaves_no_entry_and_no_change(
    platform: Platform, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, h = await as_admin(platform)
    real = record
    calls = 0

    async def second_fails(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("the store refused the second entry")
        await real(*args, **kwargs)

    monkeypatch.setattr("ops_platform.store.members.record", second_fails)
    body = {"emails": ["first@bank.test", "second@bank.test"], "role": "viewer"}
    # The ASGI test transport re-raises what the server's 500 handler answered.
    with pytest.raises(RuntimeError):
        await platform.public.post("/v1/settings/members/invite", headers=h, json=body)
    async with platform.engine.connect() as c:
        rows = (
            await c.execute(
                sa.select(sa.func.count())
                .select_from(members)
                .where(
                    members.c.team_id == h["X-Team-Id"], members.c.email.in_(["first@bank.test", "second@bank.test"])
                )
            )
        ).scalar_one()
        entries = (
            await c.execute(
                sa.select(sa.func.count())
                .select_from(audit_entries)
                .where(audit_entries.c.team_id == h["X-Team-Id"], audit_entries.c.action == "member.invite")
            )
        ).scalar_one()
    assert (rows, entries) == (0, 0)
