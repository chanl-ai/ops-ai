"""A provider's domains route sign-in only once proven by DNS (c-195), by failure mode: someone without settings.manage
verifies (F1); a listed domain routes sign-in or makes a person before it is verified (F2); verify passes with no record
or a wrong one (F3); a second workspace takes a domain another has verified (F4); another workspace's pending claim
blocks the owner (F5); saving the provider again drops a domain's verification (F6)."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from ops_platform.store.tables import users
from ops_service_kit.ids import new_id, now_iso

from .conftest import DEMO_PASSWORD, IDP, OIDC_SECRET, SignInRig


def _oidc(rig: SignInRig, *domains: str) -> dict[str, Any]:
    return {
        "kind": "oidc",
        "label": "Bank SSO",
        "domains": list(domains),
        "oidc": {"issuer": f"{IDP}/oidc/bank", "clientId": "ops-console", "clientSecretRef": OIDC_SECRET},
        "jit": {"team": rig.ops_team, "role": "chat_user"},
    }


def _check(r: Any, domain: str) -> dict[str, Any]:
    return next(c for c in r.json()["data"]["verification"] if c["domain"] == domain)


async def _other_workspace_claim(rig: SignInRig, domain: str, *, verified: bool) -> None:
    tenant, provider, now = new_id("ten"), new_id("sip"), now_iso()
    async with rig.engine.begin() as c:
        await c.execute(
            sa.text(
                "insert into tenants (id, name, status, allowed_domains, created_at) "
                "values (:t, :t, 'active', '[]', :n)"
            ),
            {"t": tenant, "n": now},
        )
        await c.execute(
            sa.text(
                "insert into signin_providers (id, tenant_id, kind, label, enabled, config, created_at, updated_at) "
                "values (:p, :t, 'saml', 'x', true, '{}', :n, :n)"
            ),
            {"p": provider, "t": tenant, "n": now},
        )
        await c.execute(
            sa.text(
                "insert into signin_domains (domain, tenant_id, provider_id, created_at, token, verified_at) "
                "values (:d, :t, :p, :n, 'theirs', :v)"
            ),
            {"d": domain, "t": tenant, "p": provider, "n": now, "v": now if verified else None},
        )


async def test_a_listed_domain_routes_nobody_until_its_record_is_verified(signin: SignInRig) -> None:
    domain = f"pend.{signin.zone}"
    r = await signin.configure("sip_pend", _oidc(signin, domain), verify=False)
    assert r.status_code == 200, r.text
    check = _check(r, domain)
    assert check["verifiedAt"] is None and check["record"]["name"] == domain
    assert check["record"]["value"].startswith("ops-ai-verify=")
    start = await signin.public.post("/v1/auth/sso/start", json={"email": f"ana@{domain}"})
    assert start.status_code == 400 and start.json()["error"]["code"] == "sso_not_enabled", start.text
    # No record, then a wrong one: refused with what DNS held.
    missing = await signin.verify_domain(domain)
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "domain_unverified", missing.text
    await signin.publish_txt(domain, "ops-ai-verify=someone-else", "v=spf1 -all")
    wrong = await signin.verify_domain(domain)
    assert wrong.status_code == 422 and "ops-ai-verify=someone-else" in wrong.json()["error"]["message"]
    ok = await signin.verify_domain(domain, check["record"]["value"])
    assert _check(ok, domain)["verifiedAt"] is not None
    done = await signin.sign_in_sso(f"ana@{domain}")
    assert done.completed is not None and done.completed.status_code == 200, done.location


async def test_a_first_sign_in_makes_nobody_at_an_unverified_domain_of_the_provider(signin: SignInRig) -> None:
    proven, pending = f"ok.{signin.zone}", f"no.{signin.zone}"
    r = await signin.configure("sip_mixed", _oidc(signin, proven), verify=True)
    assert r.status_code == 200, r.text
    assert (await signin.configure("sip_mixed", _oidc(signin, proven, pending), verify=False)).status_code == 200
    # The provider answers for someone at the pending domain: no account is made.
    done = await signin.sign_in_sso(f"start@{proven}", user=f"new@{pending}")
    assert done.completed is None or done.completed.status_code != 200
    async with signin.engine.connect() as c:
        made = (await c.execute(sa.select(users.c.id).where(users.c.email == f"new@{pending}"))).first()
    assert made is None


async def test_only_settings_manage_verifies(signin: SignInRig) -> None:
    viewer = f"view@{signin.zone}"
    await signin.person(viewer, role="viewer")
    s = await signin.public.post("/v1/auth/sign-in", json={"email": viewer, "password": DEMO_PASSWORD})
    token = s.json()["data"]["token"]
    own = (await signin.public.get("/v1/teams", headers={"Authorization": f"Bearer {token}"})).json()["data"][0]["id"]
    h = {"Authorization": f"Bearer {token}", "X-Team-Id": own}
    domain = f"perm.{signin.zone}"
    r = await signin.configure("sip_perm", _oidc(signin, domain), verify=False)
    await signin.publish_txt(domain, _check(r, domain)["record"]["value"])
    refused = await signin.verify_domain(domain, headers=h)
    assert refused.status_code == 403, refused.text
    names = await signin.public.get("/v1/settings/sign-in/secret-names", headers=signin.admin)
    assert names.json()["data"] == [OIDC_SECRET]
    assert (await signin.public.get("/v1/settings/sign-in/secret-names", headers=h)).status_code == 403


async def test_a_domain_verified_elsewhere_is_refused_and_a_pending_claim_blocks_nobody(signin: SignInRig) -> None:
    taken, squatted, raced = f"taken.{signin.zone}", f"squat.{signin.zone}", f"race.{signin.zone}"
    await _other_workspace_claim(signin, taken, verified=True)
    r = await signin.configure("sip_taken", _oidc(signin, taken))
    assert r.status_code == 409 and r.json()["error"]["code"] == "domain_taken", r.text
    await _other_workspace_claim(signin, squatted, verified=False)
    r = await signin.configure("sip_squat", _oidc(signin, squatted))
    assert r.status_code == 200, r.text
    owned = await signin.public.get("/v1/settings/sign-in/providers", headers=signin.admin)
    assert any(c["domain"] == squatted and c["verifiedAt"] for p in owned.json()["data"] for c in p["verification"])
    # Another workspace verifies between our claim and our verify: ours is refused, not doubled.
    r = await signin.configure("sip_race", _oidc(signin, raced), verify=False)
    await _other_workspace_claim(signin, raced, verified=True)
    late = await signin.verify_domain(raced)
    assert late.status_code in (409, 422)
    await signin.publish_txt(raced, _check(r, raced)["record"]["value"])
    late = await signin.public.post(f"/v1/settings/sign-in/domains/{raced}/verify", headers=signin.admin)
    assert late.status_code == 409 and late.json()["error"]["code"] == "domain_taken", late.text


async def test_saving_the_provider_again_keeps_its_verified_domains(signin: SignInRig) -> None:
    domain = f"keep.{signin.zone}"
    first = await signin.configure("sip_keep", _oidc(signin, domain))
    before = _check(first, domain)
    again = await signin.configure("sip_keep", {**_oidc(signin, domain), "label": "Renamed"}, verify=False)
    after = _check(again, domain)
    assert before["record"] == after["record"]
    listed = await signin.public.get("/v1/settings/sign-in/providers", headers=signin.admin)
    kept = next(c for p in listed.json()["data"] for c in p["verification"] if c["domain"] == domain)
    assert kept["verifiedAt"] is not None
