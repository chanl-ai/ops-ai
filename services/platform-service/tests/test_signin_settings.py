"""A workspace's sign-in providers (c-188), by failure mode (F9): a member who is not a Security team admin changes
them; a provider sends new people to a team its author may not add people to; a first sign-in makes an admin; a
domain already used by another workspace is taken over; a secret that settings do not hold is accepted and fails at
the first sign-in; another tenant's provider is reached by id."""

from __future__ import annotations

import sqlalchemy as sa

from ops_platform.store.tables import teams
from ops_service_kit.ids import new_id, now_iso

from .conftest import DEMO_PASSWORD, IDP, OIDC_SECRET, SignInRig


def _oidc(domain: str, **over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "kind": "oidc",
        "label": "Bank SSO",
        "domains": [domain],
        "oidc": {"issuer": f"{IDP}/oidc/bank", "clientId": "ops-console", "clientSecretRef": OIDC_SECRET},
    }
    return body | over


async def _headers(rig: SignInRig, email: str, team: str) -> dict[str, str]:
    r = await rig.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": team}


async def test_only_a_security_team_admin_reads_or_changes_providers(signin: SignInRig) -> None:
    # An admin of another team, but not of the Security team.
    await signin.person(f"team.admin@{signin.zone}", role="admin")
    async with signin.engine.connect() as c:
        team = (
            await c.execute(sa.text("select team_id from members where email = :e"), {"e": f"team.admin@{signin.zone}"})
        ).scalar_one()
    other = await _headers(signin, f"team.admin@{signin.zone}", team)
    assert (await signin.configure("sip_a", _oidc(f"a.{signin.zone}"), headers=other)).status_code == 403
    assert (await signin.public.get("/v1/settings/sign-in/providers", headers=other)).status_code == 403
    assert (await signin.public.delete("/v1/settings/sign-in/providers/sip_a", headers=other)).status_code == 403
    ok = await signin.configure("sip_a", _oidc(f"a.{signin.zone}"))
    assert ok.status_code == 200, ok.text
    listed = await signin.public.get("/v1/settings/sign-in/providers", headers=signin.admin)
    assert [p["id"] for p in listed.json()["data"]] == ["sip_a"]
    assert listed.json()["data"][0]["oidc"]["clientSecretRef"] == OIDC_SECRET


async def test_new_people_go_only_to_a_team_the_author_may_add_people_to(signin: SignInRig) -> None:
    foreign = new_id("team")
    async with signin.engine.begin() as c:
        await c.execute(
            teams.insert().values(
                id=foreign,
                tenant_id=signin.tenant,
                name="Lending",
                owner_groups=[],
                scope="owned",
                created_at=now_iso(),
            )
        )
    # A Security admin may set providers but holds no admin right in the Lending team.
    security_only = await signin.security_admin_only(f"sec@{signin.zone}")
    r = await signin.configure(
        "sip_b", _oidc(f"b.{signin.zone}", jit={"team": foreign, "role": "chat_user"}), headers=security_only
    )
    assert r.status_code == 403, r.text
    # A workspace admin, admin in every team, may send new people there.
    assert (
        await signin.configure("sip_b", _oidc(f"b.{signin.zone}", jit={"team": foreign, "role": "chat_user"}))
    ).status_code == 200
    r = await signin.configure("sip_b", _oidc(f"b.{signin.zone}", jit={"team": signin.ops_team, "role": "admin"}))
    assert r.status_code == 400 and r.json()["error"]["code"] == "jit_role"


async def test_a_domain_another_workspace_uses_is_refused(signin: SignInRig) -> None:
    assert (await signin.configure("sip_c", _oidc(f"c.{signin.zone}"))).status_code == 200
    # The same domain from a second provider of this workspace, then from another workspace's row.
    clash = await signin.configure("sip_c2", _oidc(f"c.{signin.zone}"))
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "domain_taken"
    other_tenant, provider = new_id("ten"), new_id("sip")
    async with signin.engine.begin() as c:
        await c.execute(
            sa.text(
                "insert into tenants (id, name, status, allowed_domains, created_at) "
                "values (:t, :t, 'active', '[]', :n)"
            ),
            {"t": other_tenant, "n": now_iso()},
        )
        await c.execute(
            sa.text(
                "insert into signin_providers (id, tenant_id, kind, label, enabled, config, created_at, updated_at) "
                "values (:p, :t, 'saml', 'x', true, '{}', :n, :n)"
            ),
            {"p": provider, "t": other_tenant, "n": now_iso()},
        )
        await c.execute(
            sa.text(
                "insert into signin_domains (domain, tenant_id, provider_id, created_at, token, verified_at) "
                "values (:d, :t, :p, :n, 'tok', :n)"
            ),
            {"d": f"d.{signin.zone}", "p": provider, "t": other_tenant, "n": now_iso()},
        )
    taken = await signin.configure("sip_d", _oidc(f"d.{signin.zone}"))
    assert taken.status_code == 409
    # Another tenant's provider id answers 404 here, not its record.
    assert (
        await signin.public.delete(f"/v1/settings/sign-in/providers/{provider}", headers=signin.admin)
    ).status_code == 404


async def test_a_secret_settings_do_not_hold_is_refused_when_saved(signin: SignInRig) -> None:
    body = _oidc(f"e.{signin.zone}")
    body["oidc"] = {"issuer": f"{IDP}/oidc/bank", "clientId": "ops-console", "clientSecretRef": "not-set"}
    r = await signin.configure("sip_e", body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "secret_missing"


async def test_a_saml_provider_needs_a_real_certificate(signin: SignInRig) -> None:
    body = {
        "kind": "saml",
        "label": "SAML",
        "domains": [f"f.{signin.zone}"],
        "saml": {
            "idpEntityId": "x",
            "ssoUrl": f"{IDP}/saml/x/sso",
            "certificate": "-----BEGIN CERTIFICATE-----" + "A" * 100,
        },
    }
    r = await signin.configure("sip_f", body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "certificate"
