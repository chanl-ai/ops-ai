"""A workspace's security and default teams, and identity provider groups (c-202), by failure mode: a non workspace
admin changes them (F1); Security admin stays with the old security team or misses the new one (F2); an archived or
another workspace's team is set (F3); a new person lands nowhere when the provider names only a role (F4); a group
mapping adds a membership twice, for a group the person does not carry, or as admin (F5)."""

from __future__ import annotations

from typing import Any

import httpx
import sqlalchemy as sa

from ops_platform.keys import dev_signer
from ops_platform.store.tables import audit_entries, members, teams
from ops_policy import Ed25519Verifier, verify
from ops_service_kit.ids import new_id, now_iso

from .conftest import DEMO_PASSWORD, IDP, OIDC_SECRET, SignInRig
from .test_team_names import service


async def _team(rig: SignInRig, name: str) -> str:
    r = await rig.public.post("/v1/settings/teams", json={"name": name, "admin": await _lead(rig)}, headers=rig.admin)
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


async def _lead(rig: SignInRig) -> str:
    email = f"{new_id('lead').lower()}@{rig.zone}"
    await rig.person(email, role="viewer")
    return email


async def _put(rig: SignInRig, body: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
    return await rig.public.put("/v1/settings/workspace-teams", json=body, headers=headers or rig.admin)


async def _roles_in(rig: SignInRig, email: str, team: str) -> list[str]:
    r = await rig.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    claims = verify(r.json()["data"]["token"], Ed25519Verifier.from_jwk(dev_signer().public_jwk(), "platform"))
    return list(claims["access"].get(team, []))  # type: ignore[union-attr]


async def test_moving_the_security_team_moves_security_admin_and_the_token_names_it(signin: SignInRig) -> None:
    risk = await _team(signin, "Risk")
    async with signin.engine.connect() as c:
        risk_lead = (
            await c.execute(sa.select(members.c.email).where(members.c.team_id == risk, members.c.role == "admin"))
        ).scalar_one()
    before = await signin.public.get("/v1/settings/workspace-teams", headers=signin.admin)
    assert before.json()["data"] == {"securityTeam": signin.security_team, "defaultTeam": None}
    assert "security_admin" not in await _roles_in(signin, risk_lead, risk)
    r = await _put(signin, {"securityTeam": risk, "defaultTeam": None})
    assert r.status_code == 200, r.text
    assert "security_admin" in await _roles_in(signin, risk_lead, risk)
    me = await signin.public.get("/v1/me", headers={"Authorization": signin.admin["Authorization"]})
    admin_email = me.json()["data"]["user"]["email"]
    assert me.json()["data"]["securityTeamId"] == risk
    assert "security_admin" not in await _roles_in(signin, admin_email, signin.security_team)
    r = await signin.public.post("/v1/auth/sign-in", json={"email": admin_email, "password": DEMO_PASSWORD})
    claims = verify(r.json()["data"]["token"], Ed25519Verifier.from_jwk(dev_signer().public_jwk(), "platform"))
    assert claims["security_team"] == risk
    # The new security team cannot be archived; the old one now can.
    assert (await signin.public.post(f"/v1/settings/teams/{risk}/archive", headers=signin.admin)).status_code == 409


async def test_only_a_workspace_admin_sets_the_workspace_teams(signin: SignInRig) -> None:
    h = await signin.security_admin_only(f"sec@{signin.zone}")
    assert (await _put(signin, {"securityTeam": signin.ops_team, "defaultTeam": None}, headers=h)).status_code == 403
    assert (await signin.public.get("/v1/settings/workspace-teams", headers=h)).status_code == 403


async def test_a_scoped_service_reads_its_own_workspaces_teams_and_no_others(signin: SignInRig) -> None:
    # A background job with no person (tools' tool access) needs the security team; a token reads only its tenant's.
    security = await _team(signin, "Security desk")
    assert (await _put(signin, {"securityTeam": security})).status_code == 200
    own = await signin.public.get("/v1/settings/workspace-teams", headers=service(["settings:view"], signin.tenant))
    assert own.status_code == 200 and own.json()["data"]["securityTeam"] == security, own.text
    other = await signin.public.get("/v1/settings/workspace-teams", headers=service(["settings:view"], "ten_other"))
    assert other.status_code == 200 and other.json()["data"]["securityTeam"] != security, other.text
    bare = await signin.public.get("/v1/settings/workspace-teams", headers=service([], signin.tenant))
    assert (bare.status_code, bare.json()["error"]["code"]) == (403, "scope_required"), bare.text


async def test_an_archived_or_foreign_team_cannot_be_set(signin: SignInRig) -> None:
    old = await _team(signin, "Old")
    assert (await signin.public.post(f"/v1/settings/teams/{old}/archive", headers=signin.admin)).status_code == 200
    r = await _put(signin, {"securityTeam": signin.security_team, "defaultTeam": old})
    assert r.status_code == 400 and r.json()["error"]["code"] == "team_not_usable", r.text
    other, theirs = new_id("ten"), new_id("team")
    async with signin.engine.begin() as c:
        await c.execute(
            sa.text(
                "insert into tenants (id, name, status, allowed_domains, created_at) "
                "values (:t, :t, 'active', '[]', :n)"
            ),
            {"t": other, "n": now_iso()},
        )
        await c.execute(
            teams.insert().values(
                id=theirs, tenant_id=other, name="Theirs", owner_groups=[], scope="owned", created_at=now_iso()
            )
        )
    assert (await _put(signin, {"securityTeam": theirs, "defaultTeam": None})).status_code == 400


def _oidc(domain: str, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "oidc",
        "label": "Bank SSO",
        "domains": [domain],
        "oidc": {"issuer": f"{IDP}/oidc/bank", "clientId": "ops-console", "clientSecretRef": OIDC_SECRET},
        **extra,
    }


async def test_a_role_with_no_team_lands_new_people_in_the_default_team(signin: SignInRig) -> None:
    lobby = await _team(signin, "Lobby")
    assert (await _put(signin, {"securityTeam": signin.security_team, "defaultTeam": lobby})).status_code == 200
    domain = f"dflt.{signin.zone}"
    r = await signin.configure("sip_default", _oidc(domain, jit={"role": "chat_user"}))
    assert r.status_code == 200, r.text
    done = await signin.sign_in_sso(f"new@{domain}")
    assert done.completed is not None and done.completed.status_code == 200, done.location
    assert done.completed.json()["data"]["principal"]["roles"] == {lobby: "chat_user"}


async def test_groups_add_each_mapped_membership_once_and_never_an_admin(signin: SignInRig) -> None:
    tellers, branch, desk = (
        await _team(signin, "Tellers"),
        await _team(signin, "Branch 12"),
        await _team(signin, "Desk"),
    )
    domain = f"grp.{signin.zone}"
    rule = {"group": "tellers", "team": tellers, "role": "viewer"}
    admin_rule = {"group": "bosses", "team": branch, "role": "admin"}
    r = await signin.configure(
        "sip_groups", _oidc(domain, jit={"role": "chat_user", "team": branch}, groups={"map": [admin_rule]})
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "group_role", r.text
    body = _oidc(
        domain,
        jit={"role": "chat_user", "team": branch},
        groups={"map": [rule, {**rule, "group": "ops", "team": desk}]},
    )
    assert (await signin.configure("sip_groups", body)).status_code == 200
    email = f"ana@{domain}"
    start = (await signin.public.post("/v1/auth/sso/start", json={"email": email})).json()["data"]
    location = await signin.answer(start["redirectUrl"] + "&groups=tellers,unmapped", user=email)
    code = httpx.URL(location).params["code"]
    done = await signin.public.post("/v1/auth/sso/complete", json={"code": code, "flowKey": start["flowKey"]})
    roles = done.json()["data"]["principal"]["roles"]
    # The JIT team with its role, plus Tellers from the group; the "ops" rule's group is not carried.
    assert roles == {branch: "chat_user", tellers: "viewer"}, roles
    again = await signin.sign_in_sso(email)
    assert again.completed is not None and again.completed.status_code == 200
    async with signin.engine.connect() as c:
        rows = (
            await c.execute(sa.select(sa.func.count()).select_from(members).where(members.c.email == email))
        ).scalar_one()
    assert rows == 2


async def test_a_workspace_admin_names_the_workspace_and_me_shows_it_with_the_change_audited(signin: SignInRig) -> None:
    r = await signin.public.patch("/v1/settings/workspace", json={"name": "Northfield Bank"}, headers=signin.admin)
    assert r.status_code == 200 and r.json()["data"]["name"] == "Northfield Bank", r.text
    me = await signin.public.get("/v1/me", headers={"Authorization": signin.admin["Authorization"]})
    assert me.json()["data"]["tenantName"] == "Northfield Bank"
    async with signin.engine.connect() as c:
        done = (
            await c.execute(
                sa.select(audit_entries.c.detail).where(
                    audit_entries.c.tenant_id == signin.tenant, audit_entries.c.action == "workspace.rename"
                )
            )
        ).all()
    assert [d.detail["to"] for d in done] == ["Northfield Bank"]


async def test_only_a_workspace_admin_names_the_workspace(signin: SignInRig) -> None:
    h = await signin.security_admin_only(f"sec2@{signin.zone}")
    assert (
        await signin.public.patch("/v1/settings/workspace", json={"name": "Someone Else"}, headers=h)
    ).status_code == 403
