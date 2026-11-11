"""Company sign-in required and break-glass accounts (decision D7): while required, a person on a verified SSO domain
gets the wrong-password refusal for any password, except the named Security admins on the break-glass list, who keep
theirs under the usual lockout. The list cannot empty, and the only provider cannot be turned off, while nobody else
could get in."""

from __future__ import annotations

from typing import Any

import httpx
import sqlalchemy as sa

from ops_access.catalogue import SECURITY_ADMIN
from ops_platform.store.tables import audit_entries, role_assignments, users
from ops_service_kit.ids import new_id, now_iso

from .conftest import DEMO_PASSWORD, IDP, SignInRig


async def _saml(rig: SignInRig, provider: str, domain: str, *, enabled: bool = True) -> httpx.Response:
    """A SAML provider for `domain`, with the password provider on beside it, so passwords follow the providers."""
    password = await rig.configure("sip_password", {"kind": "password", "label": "Password"})
    assert password.status_code == 200, password.text
    cert = (await rig.idp.get("/saml/bank/certificate")).text
    body: dict[str, Any] = {
        "kind": "saml",
        "label": "Bank SAML",
        "enabled": enabled,
        "domains": [domain],
        "saml": {"idpEntityId": f"{IDP}/saml/bank", "ssoUrl": f"{IDP}/saml/bank/sso", "certificate": cert},
    }
    return await rig.configure(provider, body)


async def _require(rig: SignInRig, on: bool) -> httpx.Response:
    return await rig.public.put("/v1/policies/companySignInRequired", json={"value": on}, headers=rig.admin)


async def _break_glass(rig: SignInRig, method: str, user: str) -> httpx.Response:
    return await rig.public.request(method, f"/v1/settings/sign-in/break-glass/{user}", headers=rig.admin)


async def _user(rig: SignInRig, email: str) -> str:
    async with rig.engine.connect() as c:
        return str((await c.execute(sa.select(users.c.id).where(users.c.email == email))).scalar_one())


async def _password(rig: SignInRig, email: str, password: str = DEMO_PASSWORD) -> httpx.Response:
    return await rig.public.post("/v1/auth/sign-in", json={"email": email, "password": password})


async def _security_admin(rig: SignInRig, email: str) -> str:
    await rig.security_admin_only(email)
    return await _user(rig, email)


async def test_a_password_skips_company_sign_in_only_for_a_break_glass_account(signin: SignInRig) -> None:
    domain = f"req.{signin.zone}"
    assert (await _saml(signin, "sip_req", domain)).status_code == 200
    staff = f"teller@{domain}"
    await signin.person(staff)
    # Company sign-in is not required yet: a password follows the providers, as before.
    assert (await _password(signin, staff)).status_code == 200
    refused = await _require(signin, True)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "break_glass_none", refused.text
    keeper = await _security_admin(signin, f"keeper@{domain}")
    assert (await _break_glass(signin, "PUT", keeper)).status_code == 200
    assert (await _require(signin, True)).status_code == 200
    wrong = await _password(signin, staff, "not-the-password")
    right = await _password(signin, staff)
    # The right password is refused exactly as a wrong one, so nothing says which it was.
    assert right.status_code == wrong.status_code == 401, right.text
    assert right.json()["error"]["code"] == wrong.json()["error"]["code"]
    assert (await _password(signin, f"keeper@{domain}")).status_code == 200
    async with signin.engine.connect() as c:
        used = (
            await c.execute(
                sa.select(sa.func.count())
                .select_from(audit_entries)
                .where(audit_entries.c.action == "signin.break_glass_used", audit_entries.c.target_id == keeper)
            )
        ).scalar_one()
    assert used == 1


async def test_the_last_break_glass_account_stays_while_company_sign_in_is_required(signin: SignInRig) -> None:
    keeper = await _security_admin(signin, f"keeper@last.{signin.zone}")
    other = await _security_admin(signin, f"second@last.{signin.zone}")
    assert (await _break_glass(signin, "PUT", keeper)).status_code == 200
    assert (await _require(signin, True)).status_code == 200
    r = await _break_glass(signin, "DELETE", keeper)
    assert r.status_code == 409 and r.json()["error"]["code"] == "break_glass_last", r.text
    assert (await _break_glass(signin, "PUT", other)).status_code == 200
    assert (await _break_glass(signin, "DELETE", keeper)).status_code == 200


async def test_only_a_security_admin_is_a_break_glass_account(signin: SignInRig) -> None:
    viewer = await signin.person(f"viewer@only.{signin.zone}")
    r = await _break_glass(signin, "PUT", viewer)
    assert r.status_code == 422 and r.json()["error"]["code"] == "break_glass_not_security_admin", r.text


async def test_turning_off_the_only_way_in_is_refused(signin: SignInRig) -> None:
    domain = f"off.{signin.zone}"
    assert (await _saml(signin, "sip_off", domain)).status_code == 200
    keeper = await _security_admin(signin, f"keeper@other.{signin.zone}")
    assert (await _break_glass(signin, "PUT", keeper)).status_code == 200
    assert (await _require(signin, True)).status_code == 200
    # The break-glass account loses Security admin, so nobody could get in with the provider off.
    async with signin.engine.begin() as c:
        await c.execute(sa.text("DELETE FROM role_assignments WHERE subject_id = :u"), {"u": keeper})
    r = await _saml(signin, "sip_off", domain, enabled=False)
    assert r.status_code == 409 and r.json()["error"]["code"] == "last_sign_in_method", r.text
    gone = await signin.public.delete("/v1/settings/sign-in/providers/sip_off", headers=signin.admin)
    assert gone.status_code == 409, gone.text


async def test_wrong_passwords_lock_a_break_glass_account_as_anyone(signin: SignInRig) -> None:
    email = f"keeper@lock.{signin.zone}"
    keeper = await _security_admin(signin, email)
    assert (await _break_glass(signin, "PUT", keeper)).status_code == 200
    codes = [(await _password(signin, email, "guess-guess-guess")).status_code for _ in range(6)]
    assert codes[-1] == 429, codes
    assert (await _password(signin, email)).status_code == 429


async def test_a_provider_never_links_a_break_glass_account_by_email(signin: SignInRig) -> None:
    domain = f"link.{signin.zone}"
    await signin.saml(domain)
    # A viewer granted Security admin in the Security team: not Admin of any team, so only the list keeps them unlinked.
    keeper = await signin.person(f"keeper@{domain}")
    async with signin.engine.begin() as c:
        await c.execute(
            role_assignments.insert().values(
                id=new_id("ras"), tenant_id=signin.tenant, subject_kind="person", subject_id=keeper,
                role_id=SECURITY_ADMIN.id, team_id=signin.security_team, granted_by="test", reason="test",
                source="grant", created_at=now_iso(),
            )
        )  # fmt: skip
    assert (await _break_glass(signin, "PUT", keeper)).status_code == 200
    done = await signin.sign_in_sso(f"keeper@{domain}")
    assert done.query == {"error": "no_access"}, done.location
