"""Sign-in, session, refresh, sign-out and the published keys (P1 to P3a, P4a), by failure mode."""

from __future__ import annotations

import httpx
import pytest
import sqlalchemy as sa

from ops_platform.api.app import create_public_app
from ops_platform.store.tables import audit_entries
from ops_policy import Ed25519Signer, Ed25519Verifier, TokenError, mint, verify

from .conftest import Platform


async def test_sign_in_issues_a_token_any_service_verifies_with_the_published_key(platform: Platform) -> None:
    p = await platform.person(roles=("admin", "viewer"))
    r = await platform.sign_in(p)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    jwks = (await platform.public.get("/.well-known/jwks.json")).json()
    claims = verify(data["token"], Ed25519Verifier.from_jwk(jwks["keys"][0], "agents"))
    assert claims["tenant_id"] == p.tenant_id and claims["sub"] == p.user_id
    assert sorted(claims["team_ids"]) == sorted(p.teams) and claims["roles"] == p.teams
    assert claims["kind"] == "person" and claims["auth_method"] == "dev"
    with pytest.raises(TokenError) as refused:
        verify(data["token"], Ed25519Verifier.from_jwk(jwks["keys"][0], "billing"))
    assert refused.value.reason == "audience"


async def test_the_published_key_set_holds_no_private_material(platform: Platform) -> None:
    r = await platform.public.get("/.well-known/jwks.json")
    assert r.status_code == 200 and "max-age" in r.headers["cache-control"]
    [key] = r.json()["keys"]
    assert key["kid"] == platform.signer.kid and "d" not in key


@pytest.mark.parametrize("password", ["wrong", ""])
async def test_a_wrong_password_is_401(platform: Platform, password: str) -> None:
    p = await platform.person()
    assert (await platform.sign_in(p, password)).status_code == 401


async def test_an_unknown_email_is_401(platform: Platform) -> None:
    r = await platform.public.post("/v1/auth/sign-in", json={"email": "nobody@bank.test", "password": "x"})
    assert r.status_code == 401


async def test_an_email_in_two_tenants_is_refused_rather_than_guessed(platform: Platform) -> None:
    a = await platform.person()
    await platform.person(email=a.email)
    assert (await platform.sign_in(a)).status_code == 401


async def test_sign_in_is_closed_when_no_demo_password_is_configured(platform: Platform) -> None:
    p = await platform.person()
    app = create_public_app(platform.store, platform.signer, demo_password=None, audiences=["platform"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://p") as c:
        r = await c.post("/v1/auth/sign-in", json={"email": p.email, "password": ""})
    assert r.status_code == 401


async def test_session_returns_the_principal_for_the_token(platform: Platform) -> None:
    p = await platform.person(roles=("builder",))
    token = (await platform.sign_in(p)).json()["data"]["token"]
    r = await platform.public.get("/v1/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    principal = r.json()["data"]
    assert principal["tenantId"] == p.tenant_id and principal["teamIds"] == list(p.teams)
    assert principal["authMethod"] == "dev" and principal["kind"] == "person"


async def test_session_refuses_no_token_and_a_token_from_another_key(platform: Platform) -> None:
    p = await platform.person()
    assert (await platform.public.get("/v1/auth/session")).status_code == 401
    forged = mint(
        {"sub": p.user_id, "tenant_id": p.tenant_id, "aud": ["platform"]},
        Ed25519Signer.generate(platform.signer.kid),
        ttl_s=60,
    )
    r = await platform.public.get("/v1/auth/session", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_refresh_rotates_and_reuse_of_a_rotated_token_ends_the_session(platform: Platform) -> None:
    p = await platform.person()
    first = (await platform.sign_in(p)).json()["data"]
    r = await platform.public.post("/v1/auth/refresh", json={"refreshToken": first["refreshToken"]})
    assert r.status_code == 200, r.text
    second = r.json()["data"]
    assert second["refreshToken"] != first["refreshToken"]

    reused = await platform.public.post("/v1/auth/refresh", json={"refreshToken": first["refreshToken"]})
    assert reused.status_code == 401
    # The reuse is treated as theft: the current refresh token and the session both stop working.
    after = await platform.public.post("/v1/auth/refresh", json={"refreshToken": second["refreshToken"]})
    assert after.status_code == 401
    r = await platform.public.get("/v1/auth/session", headers={"Authorization": f"Bearer {second['token']}"})
    assert r.status_code == 401


async def test_sign_out_ends_the_session_and_its_refresh_token(platform: Platform) -> None:
    p = await platform.person()
    data = (await platform.sign_in(p)).json()["data"]
    auth = {"Authorization": f"Bearer {data['token']}"}
    assert (await platform.public.post("/v1/auth/sign-out", headers=auth)).status_code == 204
    assert (await platform.public.get("/v1/auth/session", headers=auth)).status_code == 401
    r = await platform.public.post("/v1/auth/refresh", json={"refreshToken": data["refreshToken"]})
    assert r.status_code == 401


async def test_sign_in_and_sign_out_are_audited(platform: Platform) -> None:
    p = await platform.person()
    token = (await platform.sign_in(p)).json()["data"]["token"]
    await platform.public.post("/v1/auth/sign-out", headers={"Authorization": f"Bearer {token}"})
    async with platform.engine.connect() as c:
        rows = (
            await c.execute(
                sa.select(audit_entries.c.action, audit_entries.c.actor).where(audit_entries.c.tenant_id == p.tenant_id)
            )
        ).all()
    assert sorted(rows) == [("auth.sign_in", p.user_id), ("auth.sign_out", p.user_id)]


async def test_sign_in_rejects_unknown_fields(platform: Platform) -> None:
    p = await platform.person()
    body = {"email": p.email, "password": "x", "tenantId": p.tenant_id}
    assert (await platform.public.post("/v1/auth/sign-in", json=body)).status_code == 400
