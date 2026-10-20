"""Password sign-in and reset (c-188), by failure mode: a password kept in plain text or the demo password accepted
for a person who has one (F1); a reset link that works twice or late, or leaves the old password or old sessions alive
(F2); a password accepted where the workspace turned passwords off (F5); a refresh that turns a password session into
`dev` (F11); a reset request that tells an unknown email from a known one, or claims to send with no mail set up."""

from __future__ import annotations

import re

import httpx
import sqlalchemy as sa

from ops_platform.keys import dev_signer
from ops_platform.store.tables import password_credentials, password_resets
from ops_policy import Ed25519Verifier, verify

from .conftest import DEMO_PASSWORD, Platform, SignInRig

NEW = "a long new password 1"


async def _reset_link(rig: SignInRig, email: str) -> str:
    r = await rig.public.post("/v1/auth/password/forgot", json={"email": email})
    assert r.status_code == 204, r.text
    sent = [m for m in rig.mail.sent.values() if m.to == (email,)]
    assert len(sent) == 1, sent
    found = re.search(r"/reset-password/(prt_[A-Za-z0-9_-]+)", sent[0].body)
    assert found and sent[0].body.startswith("Someone asked") and "http://console.test/reset-password/" in sent[0].body
    return found.group(1)


async def _sign_in(rig: SignInRig, email: str, password: str) -> httpx.Response:
    return await rig.public.post("/v1/auth/sign-in", json={"email": email, "password": password})


def _claims(token: str) -> dict[str, object]:
    return verify(token, Ed25519Verifier.from_jwk(dev_signer().public_jwk(), "platform"))


async def test_a_reset_sets_a_hashed_password_that_signs_in_and_retires_the_demo_one(signin: SignInRig) -> None:
    email = f"ana@{signin.zone}"
    user = await signin.person(email)
    before = await _sign_in(signin, email, DEMO_PASSWORD)
    assert before.status_code == 200 and _claims(before.json()["data"]["token"])["auth_method"] == "dev"
    token = await _reset_link(signin, email)
    r = await signin.public.post("/v1/auth/password/reset", json={"token": token, "password": NEW})
    assert r.status_code == 204, r.text
    async with signin.engine.connect() as c:
        stored = (
            await c.execute(sa.select(password_credentials.c.hash).where(password_credentials.c.user_id == user))
        ).scalar_one()
    assert NEW not in stored and stored.startswith("pbkdf2_sha256$")
    after = await _sign_in(signin, email, NEW)
    assert after.status_code == 200 and _claims(after.json()["data"]["token"])["auth_method"] == "password"
    # Once a person has a password, the demo one no longer opens their account.
    assert (await _sign_in(signin, email, DEMO_PASSWORD)).status_code == 401
    assert (await _sign_in(signin, email, "a wrong password 12")).status_code == 401


async def test_a_reset_link_works_once_and_ends_the_sessions_before_it(signin: SignInRig) -> None:
    email = f"bo@{signin.zone}"
    await signin.person(email)
    old = (await _sign_in(signin, email, DEMO_PASSWORD)).json()["data"]
    token = await _reset_link(signin, email)
    assert (
        await signin.public.post("/v1/auth/password/reset", json={"token": token, "password": NEW})
    ).status_code == 204
    again = await signin.public.post(
        "/v1/auth/password/reset", json={"token": token, "password": "another password 12"}
    )
    assert again.status_code == 400 and again.json()["error"]["code"] == "reset_invalid"
    assert (await _sign_in(signin, email, NEW)).status_code == 200
    session = await signin.public.get("/v1/auth/session", headers={"Authorization": f"Bearer {old['token']}"})
    assert session.status_code == 401
    assert (await signin.public.post("/v1/auth/refresh", json={"refreshToken": old["refreshToken"]})).status_code == 401


async def test_an_expired_reset_link_is_refused_and_changes_nothing(signin: SignInRig) -> None:
    email = f"cy@{signin.zone}"
    await signin.person(email)
    token = await _reset_link(signin, email)
    async with signin.engine.begin() as c:
        await c.execute(password_resets.update().values(expires_at="2000-01-01T00:00:00.000Z"))
    r = await signin.public.post("/v1/auth/password/reset", json={"token": token, "password": NEW})
    assert r.status_code == 400 and r.json()["error"]["code"] == "reset_invalid"
    assert (await _sign_in(signin, email, NEW)).status_code == 401


async def test_a_short_password_is_refused_before_the_link_is_spent(signin: SignInRig) -> None:
    email = f"di@{signin.zone}"
    await signin.person(email)
    token = await _reset_link(signin, email)
    short = await signin.public.post("/v1/auth/password/reset", json={"token": token, "password": "short"})
    assert short.status_code == 400 and short.json()["error"]["code"] == "password_too_short"
    assert (
        await signin.public.post("/v1/auth/password/reset", json={"token": token, "password": NEW})
    ).status_code == 204


async def test_forgot_answers_the_same_for_an_unknown_email_and_sends_nothing(signin: SignInRig) -> None:
    r = await signin.public.post("/v1/auth/password/forgot", json={"email": f"nobody@{signin.zone}"})
    assert r.status_code == 204 and not signin.mail.sent


async def test_forgot_says_so_when_no_mail_is_set_up(platform: Platform) -> None:
    p = await platform.person()
    r = await platform.public.post("/v1/auth/password/forgot", json={"email": p.email})
    assert r.status_code == 503 and r.json()["error"]["code"] == "mail_not_configured"


async def test_a_workspace_that_turned_passwords_off_refuses_them(signin: SignInRig) -> None:
    email = f"ed@sso.{signin.zone}"
    await signin.person(email)
    token = await _reset_link(signin, email)
    assert (
        await signin.public.post("/v1/auth/password/reset", json={"token": token, "password": NEW})
    ).status_code == 204
    assert (await _sign_in(signin, email, NEW)).status_code == 200
    # The workspace now signs in through OIDC only: no password provider row.
    await signin.oidc(f"sso.{signin.zone}")
    assert (await _sign_in(signin, email, NEW)).status_code == 401
    assert (await _sign_in(signin, email, DEMO_PASSWORD)).status_code == 401
    r = await signin.public.post("/v1/auth/password/forgot", json={"email": email})
    assert r.status_code == 204 and len(signin.mail.sent) == 1
    # Turning a password provider on lets the stored password work again.
    r = await signin.configure("sip_password", {"kind": "password", "label": "Password"})
    assert r.status_code == 200, r.text
    assert (await _sign_in(signin, email, NEW)).status_code == 200


async def test_a_refresh_keeps_the_sessions_method(signin: SignInRig) -> None:
    email = f"fa@{signin.zone}"
    await signin.person(email)
    token = await _reset_link(signin, email)
    await signin.public.post("/v1/auth/password/reset", json={"token": token, "password": NEW})
    first = (await _sign_in(signin, email, NEW)).json()["data"]
    r = await signin.public.post("/v1/auth/refresh", json={"refreshToken": first["refreshToken"]})
    assert r.status_code == 200
    assert _claims(r.json()["data"]["token"])["auth_method"] == "password"
    assert r.json()["data"]["principal"]["authMethod"] == "password"


async def test_step_up_checks_the_stored_password(signin: SignInRig) -> None:
    email = f"gu@{signin.zone}"
    await signin.person(email)
    token = await _reset_link(signin, email)
    await signin.public.post("/v1/auth/password/reset", json={"token": token, "password": NEW})
    auth = {"Authorization": f"Bearer {(await _sign_in(signin, email, NEW)).json()['data']['token']}"}
    wrong = await signin.public.post("/v1/auth/step-up", json={"password": DEMO_PASSWORD}, headers=auth)
    assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "wrong_password"
    right = await signin.public.post("/v1/auth/step-up", json={"password": NEW}, headers=auth)
    assert right.status_code == 200, right.text


async def test_turning_the_only_sso_provider_off_lets_passwords_back_in(signin: SignInRig) -> None:
    email = f"ina@{signin.zone}"
    await signin.person(email)
    provider = await signin.oidc(f"off.{signin.zone}")
    assert (await _sign_in(signin, email, DEMO_PASSWORD)).status_code == 401
    body = {
        "kind": "oidc",
        "label": "Bank SSO",
        "enabled": False,
        "domains": [f"off.{signin.zone}"],
        "oidc": {"issuer": "http://idp.test/oidc/bank", "clientId": "ops-console", "clientSecretRef": "bank-oidc"},
    }
    assert (await signin.configure(provider, body)).status_code == 200
    assert (await _sign_in(signin, email, DEMO_PASSWORD)).status_code == 200
    options = await signin.public.post("/v1/auth/options", json={"email": f"x@off.{signin.zone}"})
    assert options.json()["data"] == {"password": True, "sso": None}
