"""POST /v1/auth/step-up, by failure mode: the token it issues verifies under another service's audience as a
step-up for the signed-in person; a wrong password is refused with its code; the token lives five minutes; and a
step-up never passes as a session."""

from __future__ import annotations

import time

import pytest
import sqlalchemy as sa

from ops_platform.store.tables import audit_entries
from ops_policy import Ed25519Verifier, TokenError, verify

from .conftest import DEMO_PASSWORD, Platform


async def signed_in(platform: Platform) -> tuple[dict[str, str], str, str]:
    p = await platform.person(roles=("approver",))
    token = (await platform.sign_in(p)).json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}, p.user_id, p.email


async def test_the_right_password_issues_a_step_up_another_service_verifies_for_that_person(
    platform: Platform,
) -> None:
    auth, user_id, email = await signed_in(platform)
    r = await platform.public.post("/v1/auth/step-up", json={"password": DEMO_PASSWORD}, headers=auth)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    jwks = (await platform.public.get("/.well-known/jwks.json")).json()
    claims = verify(data["token"], Ed25519Verifier.from_jwk(jwks["keys"][0], "agents"))
    assert claims["typ"] == "step_up" and claims["kind"] == "step_up"
    assert claims["sub"] == user_id and claims["email"] == email
    assert claims["exp"] - claims["iat"] == 300
    async with platform.engine.connect() as c:
        actions = (
            (await c.execute(sa.select(audit_entries.c.action).where(audit_entries.c.actor == user_id))).scalars().all()
        )
    assert "auth.step_up" in actions


@pytest.mark.parametrize("password", ["wrong", ""])
async def test_a_wrong_password_is_401_with_its_code(platform: Platform, password: str) -> None:
    auth, _, _ = await signed_in(platform)
    r = await platform.public.post("/v1/auth/step-up", json={"password": password}, headers=auth)
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "wrong_password"


async def test_no_session_is_401_before_the_password_is_looked_at(platform: Platform) -> None:
    r = await platform.public.post("/v1/auth/step-up", json={"password": DEMO_PASSWORD})
    assert r.status_code == 401


async def test_a_step_up_expires_after_five_minutes(platform: Platform) -> None:
    auth, _, _ = await signed_in(platform)
    token = (await platform.public.post("/v1/auth/step-up", json={"password": DEMO_PASSWORD}, headers=auth)).json()[
        "data"
    ]["token"]
    verifier = platform.signer.verifier("agents")
    verify(token, verifier, now=time.time() + 299)
    with pytest.raises(TokenError) as refused:
        verify(token, verifier, now=time.time() + 301)
    assert refused.value.reason == "expired"


async def test_a_step_up_is_not_a_session(platform: Platform) -> None:
    auth, _, _ = await signed_in(platform)
    token = (await platform.public.post("/v1/auth/step-up", json={"password": DEMO_PASSWORD}, headers=auth)).json()[
        "data"
    ]["token"]
    r = await platform.public.get("/v1/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
