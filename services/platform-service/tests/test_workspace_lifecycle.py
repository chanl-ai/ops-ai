"""Workspace and team danger zones (c-529), by failure mode: someone other than the owner transfers, closes or restores
the workspace, or an Admin's every-cell grid reaches the owner's cell; the owner leaves or is removed and the workspace
has no owner; two transfers both win; a closed workspace still answers a member, a key or a service token; a restore
after the purge has started; the purge takes audit entries or team rows; the last admin leaves a team; a team with a
live workflow, or archived too recently, is deleted; agents-service does not answer and a delete goes ahead anyway; a
route that changes a workspace or team writes no audit entry."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from ops_access import ANY_TEAM, BUILTIN_ROLES
from ops_access.catalogue import ADMIN
from ops_identity import dev_service_signer, mint_service_token
from ops_platform.store.audit import KIND, ROUTE_ACTIONS
from ops_platform.store.lifecycle import LifecycleStore
from ops_platform.store.tables import api_keys, audit_entries, members, role_assignments, teams, tenants
from ops_platform.store.tenancy import TenantDb
from ops_platform.team_usage import TeamUsage, UsageUnavailable, team_usage
from ops_platform.workspace_lifecycle import WorkspacePurge
from ops_service_kit.ids import new_id, now_iso

from .conftest import DEMO_PASSWORD, SignInRig


@dataclass
class FakeUsage:
    """agents-service's answer per team: runs in progress and live workflow names."""

    runs: dict[str, int] = field(default_factory=dict[str, int])
    live: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    down: bool = False

    async def of(self, tenant_id: str, team_id: str) -> TeamUsage:
        if self.down:
            raise UsageUnavailable("agents-service did not answer")
        return TeamUsage(runs_in_progress=self.runs.get(team_id, 0), live_workflows=self.live.get(team_id, []))


@pytest.fixture
def usage(signin: SignInRig) -> Iterator[FakeUsage]:
    fake = FakeUsage()
    signin.app.dependency_overrides[team_usage] = lambda: fake
    yield fake
    signin.app.dependency_overrides.pop(team_usage, None)


async def _user_of(rig: SignInRig, headers: dict[str, str]) -> str:
    me = await rig.public.get("/v1/me", headers={"Authorization": headers["Authorization"]})
    assert me.status_code == 200, me.text
    return str(me.json()["data"]["user"]["id"])


async def _owner(rig: SignInRig) -> str:
    """The rig's admin made the owner, as the bootstrap and the migration do for a workspace's first admin."""
    admin = await _user_of(rig, rig.admin)
    async with rig.engine.begin() as c:
        await c.execute(
            role_assignments.insert().values(
                id=new_id("ras"), tenant_id=rig.tenant, subject_kind="person", subject_id=admin, role_id="owner",
                team_id=ANY_TEAM, granted_by="test", reason="owner", source="grant", created_at=now_iso(),
            )
        )  # fmt: skip
    return admin


async def _signed_in(rig: SignInRig, email: str) -> dict[str, str]:
    r = await rig.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


async def _account_admin(rig: SignInRig, email: str) -> tuple[str, dict[str, str]]:
    user = await rig.person(email, role="admin")
    async with rig.engine.begin() as c:
        await c.execute(
            role_assignments.insert().values(
                id=new_id("ras"), tenant_id=rig.tenant, subject_kind="person", subject_id=user, role_id="admin",
                team_id=ANY_TEAM, granted_by="test", reason="account admin", source="grant", created_at=now_iso(),
            )
        )  # fmt: skip
    return user, await _signed_in(rig, email)


async def _audit(rig: SignInRig, action: str) -> int:
    async with rig.engine.connect() as c:
        q = sa.select(sa.func.count()).where(audit_entries.c.tenant_id == rig.tenant, audit_entries.c.action == action)
        return int((await c.execute(q)).scalar_one())


def _code(r: Any) -> str:
    return str(r.json()["error"]["code"])


def test_admin_holds_no_workspace_cell_and_owner_holds_only_it() -> None:
    assert not [g for g in ADMIN.grants if g[0] == "workspace"]
    owner = next(r for r in BUILTIN_ROLES if r.id == "owner")
    assert owner.grants == (("workspace", "manage", "all"),)
    assert all(not [g for g in r.grants if g[0] == "workspace"] for r in BUILTIN_ROLES if r.id != "owner")


async def test_only_the_owner_transfers_and_only_to_an_account_admin(signin: SignInRig, usage: FakeUsage) -> None:
    owner = await _owner(signin)
    target, target_h = await _account_admin(signin, f"maya@{signin.zone}")
    plain = await signin.person(f"plain@{signin.zone}", role="admin")
    # An account admin who is not the owner is refused by can(): Admin holds no workspace cell.
    r = await signin.public.post("/v1/workspace/transfer", json={"userId": owner}, headers=target_h)
    assert r.status_code == 403, r.text
    r = await signin.public.post("/v1/workspace/transfer", json={"userId": plain}, headers=signin.admin)
    assert r.status_code == 409 and _code(r) == "not_an_account_admin", r.text
    r = await signin.public.post("/v1/workspace/transfer", json={"userId": target}, headers=signin.admin)
    assert r.status_code == 200, r.text
    me = (await signin.public.get("/v1/me", headers=target_h)).json()["data"]
    assert me["workspace"]["ownerUserId"] == target, me
    assert await _audit(signin, "workspace.transfer") == 1
    # The old owner stays an account admin and is no longer the owner.
    r = await signin.public.post("/v1/workspace/transfer", json={"userId": owner}, headers=signin.admin)
    assert r.status_code == 403, r.text


async def test_two_transfers_at_once_leave_one_owner(signin: SignInRig, usage: FakeUsage) -> None:
    await _owner(signin)
    a, _ = await _account_admin(signin, f"a@{signin.zone}")
    b, _ = await _account_admin(signin, f"b@{signin.zone}")
    results = await asyncio.gather(
        signin.public.post("/v1/workspace/transfer", json={"userId": a}, headers=signin.admin),
        signin.public.post("/v1/workspace/transfer", json={"userId": b}, headers=signin.admin),
    )
    assert sorted(r.status_code for r in results)[0] == 200, [r.text for r in results]
    async with signin.engine.connect() as c:
        owners = (
            await c.execute(
                sa.select(role_assignments.c.subject_id).where(
                    role_assignments.c.tenant_id == signin.tenant, role_assignments.c.role_id == "owner"
                )
            )
        ).all()
    assert len(owners) == 1, owners


async def test_the_owner_cannot_leave_be_removed_or_be_demoted(signin: SignInRig, usage: FakeUsage) -> None:
    owner = await _owner(signin)
    r = await signin.public.post("/v1/workspace/leave", headers=signin.admin)
    assert r.status_code == 409 and _code(r) == "owner_must_transfer", r.text
    async with signin.engine.connect() as c:
        q = sa.select(members.c.id).where(members.c.team_id == signin.ops_team, members.c.user_id == owner)
        member = str((await c.execute(q)).scalar_one())
    _, other_h = await _account_admin(signin, f"other@{signin.zone}")
    in_ops = {**other_h, "X-Team-Id": signin.ops_team}
    r = await signin.public.post("/v1/settings/members/delete", json={"ids": [member]}, headers=in_ops)
    assert r.status_code == 409 and _code(r) == "owner_must_transfer", r.text
    r = await signin.public.post("/v1/settings/members/role", json={"ids": [member], "role": "viewer"}, headers=in_ops)
    assert r.status_code == 409 and _code(r) == "owner_must_transfer", r.text


async def test_a_member_leaves_the_workspace_and_loses_every_team(signin: SignInRig, usage: FakeUsage) -> None:
    await _owner(signin)
    email = f"leaver@{signin.zone}"
    await signin.person(email, role="builder")
    h = await _signed_in(signin, email)
    r = await signin.public.post("/v1/workspace/leave", headers=h)
    assert r.status_code == 204, r.text
    assert (await signin.public.get("/v1/teams", headers=h)).status_code == 401, "their session ended"
    again = await _signed_in(signin, email)
    assert (await signin.public.get("/v1/teams", headers=again)).json()["data"] == [], "no team is left"
    assert await _audit(signin, "workspace.leave") == 1


async def test_close_refuses_a_run_in_progress_a_wrong_name_and_an_unknown_answer(
    signin: SignInRig, usage: FakeUsage
) -> None:
    await _owner(signin)
    r = await signin.public.post("/v1/workspace/close", json={"name": "not it"}, headers=signin.admin)
    assert r.status_code == 400 and _code(r) == "name_mismatch", r.text
    usage.runs[signin.ops_team] = 1
    r = await signin.public.post("/v1/workspace/close", json={"name": signin.tenant}, headers=signin.admin)
    assert r.status_code == 409 and _code(r) == "runs_in_progress", r.text
    usage.runs.clear()
    usage.down = True
    r = await signin.public.post("/v1/workspace/close", json={"name": signin.tenant}, headers=signin.admin)
    assert r.status_code == 503 and _code(r) == "usage_unavailable", r.text


async def test_a_closed_workspace_answers_only_its_owner_until_restored(signin: SignInRig, usage: FakeUsage) -> None:
    await _owner(signin)
    email = f"member@{signin.zone}"
    await signin.person(email, role="builder")
    member_h = await _signed_in(signin, email)
    in_ops = {**signin.admin, "X-Team-Id": signin.ops_team}
    key = await signin.public.post("/v1/api-keys", json={"name": "k", "scopes": ["read"]}, headers=in_ops)
    assert key.status_code == 201, key.text
    service = mint_service_token(
        dev_service_signer(), service="agents", audience="platform", tenant_id=signin.tenant, scopes=["settings:view"]
    )
    r = await signin.public.post("/v1/workspace/close", json={"name": signin.tenant}, headers=signin.admin)
    assert r.status_code == 200, r.text
    assert await _audit(signin, "workspace.close") == 1
    # A member's session and sign-in are refused; the owner reads /v1/me and sees the workspace closed.
    r = await signin.public.get("/v1/teams", headers=member_h)
    assert r.status_code in (401, 403), r.text
    r = await signin.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 403 and _code(r) == "workspace_closed", r.text
    me = (await signin.public.get("/v1/me", headers=signin.admin)).json()["data"]
    assert me["workspace"]["status"] == "closed" and me["workspace"]["purgeAfter"], me
    r = await signin.public.get("/v1/settings/members", headers=in_ops)
    assert r.status_code == 403 and _code(r) == "workspace_closed", r.text
    r = await signin.public.get("/v1/team-names", headers={"Authorization": f"Bearer {service}"})
    assert r.status_code == 403 and _code(r) == "workspace_closed", r.text
    async with signin.engine.connect() as c:
        disabled = (
            (await c.execute(sa.select(api_keys.c.disabled_at).where(api_keys.c.tenant_id == signin.tenant)))
            .scalars()
            .all()
        )
    assert disabled and all(disabled), disabled
    r = await signin.public.post("/v1/workspace/restore", headers=signin.admin)
    assert r.status_code == 200, r.text
    r = await signin.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    async with signin.engine.connect() as c:
        disabled = (
            (await c.execute(sa.select(api_keys.c.disabled_at).where(api_keys.c.tenant_id == signin.tenant)))
            .scalars()
            .all()
        )
    assert not any(disabled), disabled


async def test_the_purge_keeps_audit_entries_and_team_rows_and_refuses_a_late_restore(
    signin: SignInRig, usage: FakeUsage
) -> None:
    await _owner(signin)
    r = await signin.public.post("/v1/workspace/close", json={"name": signin.tenant}, headers=signin.admin)
    assert r.status_code == 200, r.text
    async with signin.engine.begin() as c:
        await c.execute(
            tenants.update().where(tenants.c.id == signin.tenant).values(closed_at="2000-01-01T00:00:00.000Z")
        )
    audit_before = await _audit(signin, "workspace.close")
    # The loop's own path: the pre-tenant lookup runs as the tenant role, so row-level security applies.
    store = LifecycleStore(TenantDb(signin.engine), security_team=signin.security_team)
    assert signin.tenant in await store.purge_due(restore_days=30)
    assert await WorkspacePurge(store, restore_days=30).once() >= 1
    async with signin.engine.connect() as c:
        status = (await c.execute(sa.select(tenants.c.status).where(tenants.c.id == signin.tenant))).scalar_one()
        team_states = (
            (await c.execute(sa.select(teams.c.status).where(teams.c.tenant_id == signin.tenant))).scalars().all()
        )
    assert status == "purged" and team_states and set(team_states) == {"deleted"}, (status, team_states)
    assert await _audit(signin, "workspace.close") == audit_before
    assert await _audit(signin, "workspace.purge") == 1
    r = await signin.public.post("/v1/workspace/restore", headers=signin.admin)
    assert r.status_code in (401, 403, 409), r.text


async def test_the_last_admin_cannot_leave_a_team(signin: SignInRig, usage: FakeUsage) -> None:
    email = f"solo@{signin.zone}"
    await signin.person(email, role="admin")
    h = await _signed_in(signin, email)
    team = (await signin.public.get("/v1/teams", headers=h)).json()["data"][0]["id"]
    r = await signin.public.post(f"/v1/settings/teams/{team}/leave", headers=h)
    assert r.status_code == 409 and _code(r) == "last_admin", r.text
    builder = f"b2@{signin.zone}"
    await signin.person(builder, role="builder")
    bh = await _signed_in(signin, builder)
    bteam = (await signin.public.get("/v1/teams", headers=bh)).json()["data"][0]["id"]
    r = await signin.public.post(f"/v1/settings/teams/{bteam}/leave", headers=bh)
    assert r.status_code == 204, r.text
    assert await _audit(signin, "team.leave") == 1


async def test_a_team_is_deleted_only_archived_long_enough_with_no_live_workflow(
    signin: SignInRig, usage: FakeUsage
) -> None:
    await signin.person(f"lead@{signin.zone}", role="viewer")
    body = {"name": f"Claims {new_id('x')[-6:]}", "admin": f"lead@{signin.zone}"}
    r = await signin.public.post("/v1/settings/teams", json=body, headers=signin.admin)
    assert r.status_code == 201, r.text
    team = str(r.json()["data"]["id"])
    r = await signin.public.delete(f"/v1/settings/teams/{team}", headers=signin.admin)
    assert r.status_code == 409 and _code(r) == "not_archived", r.text
    assert (await signin.public.post(f"/v1/settings/teams/{team}/archive", headers=signin.admin)).status_code == 200
    r = await signin.public.delete(f"/v1/settings/teams/{team}", headers=signin.admin)
    assert r.status_code == 409 and _code(r) == "archived_too_recently", r.text
    async with signin.engine.begin() as c:
        await c.execute(teams.update().where(teams.c.id == team).values(archived_at="2000-01-01T00:00:00.000Z"))
    usage.live[team] = ["Insurance claim intake"]
    check = (await signin.public.get(f"/v1/settings/teams/{team}/delete-check", headers=signin.admin)).json()["data"]
    assert (
        check["liveWorkflows"] == ["Insurance claim intake"] and check["usageKnown"] is True and not check["canDelete"]
    ), check
    r = await signin.public.delete(f"/v1/settings/teams/{team}", headers=signin.admin)
    assert r.status_code == 409 and _code(r) == "live_workflows", r.text
    usage.live.clear()
    usage.down = True
    check = (await signin.public.get(f"/v1/settings/teams/{team}/delete-check", headers=signin.admin)).json()["data"]
    assert check["usageKnown"] is False and not check["canDelete"], check
    r = await signin.public.delete(f"/v1/settings/teams/{team}", headers=signin.admin)
    assert r.status_code == 503 and _code(r) == "usage_unavailable", r.text
    usage.down = False
    r = await signin.public.delete(f"/v1/settings/teams/{team}", headers=signin.admin)
    assert r.status_code == 204, r.text
    async with signin.engine.connect() as c:
        status = (await c.execute(sa.select(teams.c.status).where(teams.c.id == team))).scalar_one()
    assert status == "deleted"
    assert await _audit(signin, "team.delete") == 1
    listed = (await signin.public.get("/v1/settings/teams", headers=signin.admin)).json()["data"]["data"]
    assert team not in [t["id"] for t in listed]
    again = await signin.public.post("/v1/settings/teams", json=body, headers=signin.admin)
    assert again.status_code == 201, "a deleted team's name is free again: " + again.text


async def test_the_security_team_is_never_deleted(signin: SignInRig, usage: FakeUsage) -> None:
    r = await signin.public.delete(f"/v1/settings/teams/{signin.security_team}", headers=signin.admin)
    assert r.status_code == 409 and _code(r) == "security_team", r.text


WORKSPACE_ROUTES = (
    "/v1/settings/workspace",
    "/v1/settings/teams",
    "/v1/settings/members",
    "/v1/teams",
    "/v1/workspace",
)
SRC = Path(__file__).resolve().parents[1] / "src" / "ops_platform"


def test_every_route_that_changes_a_workspace_or_team_names_the_audit_action_it_writes(signin: SignInRig) -> None:
    """The route-table walk: each changing route under the workspace and team paths is in ROUTE_ACTIONS with an
    action the audit page names (KIND) and some store writes."""
    changing = sorted(
        (m, str(getattr(r, "path", "")))
        for r in signin.app.routes
        if str(getattr(r, "path", "")).startswith(WORKSPACE_ROUTES)
        for m in (getattr(r, "methods", None) or ())
        if m in ("POST", "PUT", "PATCH", "DELETE")
    )
    assert changing, "the walk found no routes"
    written = "\n".join(p.read_text() for p in SRC.rglob("*.py") if p.name != "audit.py")
    missing = [pair for pair in changing if ROUTE_ACTIONS.get(pair) not in KIND]
    unwritten = [a for a in ROUTE_ACTIONS.values() if f'"{a}"' not in written]
    assert not missing and not unwritten, (missing, unwritten)
