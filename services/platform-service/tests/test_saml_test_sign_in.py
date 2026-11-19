"""A test sign-in (design section 7, step 2): an admin signs in at the provider as themself, and sees what came back
(email, name, groups) or which check failed. It starts no session, links or makes nobody and changes no membership; it
runs while the provider is off; only the admin who started it reads its result."""

from __future__ import annotations

from typing import Any

import httpx
import sqlalchemy as sa

from ops_platform.store.tables import members, sessions, signin_identities, users

from .conftest import IDP, SignInRig


async def _provider(rig: SignInRig, provider: str, domain: str, *, enabled: bool) -> None:
    cert = (await rig.idp.get("/saml/bank/certificate")).text
    body: dict[str, Any] = {
        "kind": "saml",
        "label": "Bank SAML",
        "enabled": enabled,
        "domains": [domain],
        "saml": {"idpEntityId": f"{IDP}/saml/bank", "ssoUrl": f"{IDP}/saml/bank/sso", "certificate": cert},
        "jit": {"team": rig.ops_team, "role": "chat_user"},
        "groups": {"map": [{"group": "tellers", "team": rig.ops_team, "role": "viewer"}]},
    }
    r = await rig.configure(provider, body)
    assert r.status_code == 200, r.text


async def _test(rig: SignInRig, provider: str, email: str, extra: str = "", **at_idp: Any) -> tuple[str, str]:
    """Runs a test sign-in as `email`; returns the flow id and the console URL the browser was sent to."""
    r = await rig.public.post(f"/v1/settings/sign-in/providers/{provider}/test", headers=rig.admin)
    assert r.status_code == 200, r.text
    started = r.json()["data"]
    location = await rig.answer(started["redirectUrl"] + extra, user=email, **at_idp)
    return str(started["flowId"]), location


async def _rows(rig: SignInRig, email: str) -> tuple[int, int, int, int]:
    async with rig.engine.connect() as c:

        async def count(q: Any) -> int:
            return int((await c.execute(q)).scalar_one())

        user = sa.select(users.c.id).where(users.c.email == email).scalar_subquery()
        return (
            await count(sa.select(sa.func.count()).select_from(users).where(users.c.email == email)),
            await count(sa.select(sa.func.count()).select_from(members).where(members.c.email == email)),
            await count(
                sa.select(sa.func.count()).select_from(signin_identities).where(signin_identities.c.user_id == user)
            ),
            await count(sa.select(sa.func.count()).select_from(sessions).where(sessions.c.user_id == user)),
        )


async def test_a_test_sign_in_shows_what_came_back_and_writes_nothing(signin: SignInRig) -> None:
    domain = f"try.{signin.zone}"
    # Off: a test runs before anyone can sign in through the provider.
    await _provider(signin, "sip_try", domain, enabled=False)
    email = f"new.person@{domain}"
    flow, location = await _test(signin, "sip_try", email, "&groups=tellers,desk")
    # JIT and a matching group rule are on, yet nobody was made, linked, given a membership or a session.
    assert await _rows(signin, email) == (0, 0, 0, 0)
    assert httpx.URL(location).path == "/settings/security/sign-in" and httpx.URL(location).params["test"] == flow
    r = await signin.public.get(f"/v1/settings/sign-in/test-results/{flow}", headers=signin.admin)
    assert r.status_code == 200, r.text
    result = r.json()["data"]
    assert result["state"] == "ok" and result["email"] == email and result["groups"] == ["tellers", "desk"], result


async def test_a_failed_test_names_the_check_and_only_its_admin_reads_it(signin: SignInRig) -> None:
    domain = f"bad.{signin.zone}"
    # Another Security admin, signed in by password before the provider is on.
    other = await signin.security_admin_only(f"sec@{signin.zone}")
    await _provider(signin, "sip_bad", domain, enabled=True)
    # The answer comes from another provider than the one saved: the signature check fails.
    flow, _ = await _test(signin, "sip_bad", f"ana@{domain}", idp_path="/saml/other/sso")
    r = await signin.public.get(f"/v1/settings/sign-in/test-results/{flow}", headers=signin.admin)
    result = r.json()["data"]
    assert result["state"] == "refused" and result["reason"], result
    assert (await signin.public.get(f"/v1/settings/sign-in/test-results/{flow}", headers=other)).status_code == 404
