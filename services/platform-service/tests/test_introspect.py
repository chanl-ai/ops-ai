"""API-key introspection lives only on the internal app and needs the service token (P4, I8, I13)."""

from __future__ import annotations

from ops_identity import mint_service_token
from ops_policy import Ed25519Signer

from .conftest import CALLER, SERVICE, Platform


async def test_introspect_is_not_served_by_the_public_app(platform: Platform) -> None:
    p = await platform.person()
    key = await platform.api_key(p)
    r = await platform.public.post("/v1/auth/introspect", json={"apiKey": key}, headers=SERVICE)
    assert r.status_code == 404


async def test_introspect_needs_the_service_token(platform: Platform) -> None:
    p = await platform.person()
    key = await platform.api_key(p)
    assert (await platform.internal.post("/v1/auth/introspect", json={"apiKey": key})).status_code == 401
    person = (await platform.sign_in(p)).json()["data"]["token"]
    stranger = Ed25519Signer.generate("svc-stranger-1")
    impostor = mint_service_token(CALLER, service="tools", audience="platform", tenant_id=None)
    for token in (
        "not-a-token",
        person,
        mint_service_token(stranger, service="agents", audience="platform", tenant_id=None),
        impostor,
    ):
        r = await platform.internal.post(
            "/v1/auth/introspect", json={"apiKey": key}, headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 401, token[:20]


async def test_a_valid_key_resolves_to_its_team_and_scopes(platform: Platform) -> None:
    p = await platform.person(roles=("admin",))
    key = await platform.api_key(p, scopes=("read", "write"))
    r = await platform.internal.post("/v1/auth/introspect", json={"apiKey": key}, headers=SERVICE)
    assert r.status_code == 200, r.text
    principal = r.json()["data"]
    assert principal["kind"] == "api_key" and principal["authMethod"] == "api_key"
    assert principal["tenantId"] == p.tenant_id and principal["teamId"] == next(iter(p.teams))
    assert principal["teamIds"] == [next(iter(p.teams))] and principal["scopes"] == ["read", "write"]


async def test_a_wrong_revoked_or_disabled_key_is_401(platform: Platform) -> None:
    p = await platform.person()
    good = await platform.api_key(p)
    wrong = good.rsplit(".", 1)[0] + ".not-the-secret"
    revoked = await platform.api_key(p, revoked_at="2026-01-01T00:00:00Z")
    disabled = await platform.api_key(p, disabled_at="2026-01-01T00:00:00Z")
    for key in (wrong, revoked, disabled, "ok_missing.secret", "not-a-key"):
        r = await platform.internal.post("/v1/auth/introspect", json={"apiKey": key}, headers=SERVICE)
        assert r.status_code == 401, key
