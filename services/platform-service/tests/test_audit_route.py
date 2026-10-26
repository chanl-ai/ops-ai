"""Reading the audit log (P12, I7), by failure mode: a non-admin reads it, a team reads another team's entries, the
filters let rows through that do not match, a row the console cannot show without a second request, and a write that
fails part-way leaves entries behind."""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa

from ops_platform.store.audit import record
from ops_platform.store.tables import audit_entries, members, teams

from .conftest import Platform
from .test_members import as_admin, invite_one, join, member_rows
from .test_permissions import grant


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


async def test_an_entry_names_its_actor_team_and_target_and_reads_as_a_sentence(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    token = await invite_one(platform, h, "named@bank.test", role="approver")
    r = await platform.public.post(f"/v1/invites/{token}/accept", json={"name": "Nam Ed"})
    assert r.status_code == 200, r.text
    [invited] = (await audit(platform, h, kind="invited"))["data"]
    assert (invited["actorEmail"], invited["targetName"]) == (admin.email, "named@bank.test"), invited
    assert invited["actorName"] and invited["team"], invited
    assert invited["summary"] == "Invited named@bank.test as reviewer", invited["summary"]
    [joined] = (await audit(platform, h, kind="joined"))["data"]
    assert (joined["actorName"], joined["kind"]) == ("Nam Ed", "joined"), joined
    assert joined["summary"] == "named@bank.test accepted the invitation and joined", joined["summary"]


async def test_the_views_and_facets_count_the_teams_entries(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    await invite_one(platform, h, "a@bank.test")
    await invite_one(platform, h, "b@bank.test")
    removed = [m["id"] for m in await member_rows(platform, h) if m["email"] == "b@bank.test"]
    gone = await platform.public.post("/v1/settings/members/delete", headers=h, json={"ids": removed})
    assert gone.status_code == 200, gone.text
    # An entry outside the access view, in the same team: a sign-in.
    async with platform.engine.begin() as c:
        await record(
            c,
            tenant_id=admin.tenant_id,
            team_id=h["X-Team-Id"],
            actor=admin.user_id,
            action="auth.sign_in",
            target_kind="session",
            target_id="ses_test",
            request_id="req_test",
            detail={},
        )
    page = await audit(platform, h, view="access")
    assert {e["action"] for e in page["data"]} == {"member.invite", "member.remove"}, page["data"]
    assert page["facets"]["action"] == {"invited": 2, "deleted": 1, "login": 1}, page["facets"]
    counts = page["viewCounts"]
    assert counts == {"all": 4, "access": 3, "deletions": 1, "publishes": 0}, counts
    assert [e["action"] for e in (await audit(platform, h, view="deletions"))["data"]] == ["member.remove"]


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


async def test_no_team_reads_another_teams_entries_and_only_the_account_admin_reads_the_accounts(
    platform: Platform,
) -> None:
    """c-507 (owner's answer Q1): a team's audit page lists that team's entries only, whatever its scope; the entries
    no team holds (sign-ins, membership) show only to the account admin, who holds audit in every team."""
    admin, h = await as_admin(platform)
    async with platform.engine.begin() as c:
        await c.execute(teams.update().where(teams.c.id == h["X-Team-Id"]).values(scope="all"))
    neighbour = await platform.person(roles=("admin",), tenant_id=admin.tenant_id)
    token = (await platform.sign_in(neighbour)).json()["data"]["token"]
    await invite_one(platform, {"Authorization": f"Bearer {token}"}, "elsewhere@bank.test")
    teams_seen = {e["teamId"] for e in (await audit(platform, h))["data"]}
    assert teams_seen <= {h["X-Team-Id"]}, "neither another team's entries nor the account's"
    await grant(platform, admin, "*", "admin")
    actions = {(e["action"], e["teamId"]) for e in (await audit(platform, h))["data"]}
    assert ("auth.sign_in", None) in actions, "the account admin reads the account's entries"
    assert ("member.invite", next(iter(neighbour.teams))) not in actions, "and still no other team's"


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
    res = await platform.public.post("/v1/settings/members/invite", headers=h, json=body)
    assert res.status_code == 500 and res.json()["error"]["code"] == "internal"
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
