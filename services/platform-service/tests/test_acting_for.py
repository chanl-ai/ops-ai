"""Acting-for tokens (c-558), by failure mode: a token is minted for a person outside the call's team, a token for a
member names the wrong person or service or could pass as a session, and a service token naming no tenant is
answered for some tenant."""

from __future__ import annotations

from ops_identity import mint_service_token
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import verify

from .conftest import CALLER, Platform


def service(tenant: str | None, team: str | None = None) -> dict[str, str]:
    token = mint_service_token(
        CALLER, service="agents", audience="platform", tenant_id=tenant, team_id=team, ttl_s=TEST_TOKEN_TTL_S
    )
    return {"Authorization": f"Bearer {token}"}


async def test_a_person_outside_the_team_gets_no_acting_for_token(platform: Platform) -> None:
    member = await platform.person(roles=("builder",))
    outsider = await platform.person(roles=("builder",), tenant_id=member.tenant_id)
    team = next(iter(member.teams))
    r = await platform.internal.post(
        "/v1/acting-for-tokens", json={"email": outsider.email}, headers=service(member.tenant_id, team)
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_a_member", r.text
    # Nobody of another tenant either, by an email that exists there.
    elsewhere = await platform.person(roles=("builder",))
    r = await platform.internal.post(
        "/v1/acting-for-tokens", json={"email": elsewhere.email}, headers=service(member.tenant_id, team)
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_a_member", r.text


async def test_a_members_token_names_them_the_team_and_the_service_and_is_not_a_session(platform: Platform) -> None:
    member = await platform.person(roles=("builder",))
    team = next(iter(member.teams))
    r = await platform.internal.post(
        "/v1/acting-for-tokens", json={"email": member.email}, headers=service(member.tenant_id, team)
    )
    assert r.status_code == 200, r.text
    claims = verify(r.json()["data"]["token"], platform.signer.verifier("tools"))
    assert (claims["sub"], claims["team_id"], claims["tenant_id"]) == (member.user_id, team, member.tenant_id)
    assert claims["kind"] == "acting_for" and claims["act"] == {"sub": "service:agents"}
    assert claims["exp"] - claims["iat"] == 60


async def test_a_service_token_naming_no_tenant_or_team_is_refused(platform: Platform) -> None:
    member = await platform.person(roles=("builder",))
    r = await platform.internal.post(
        "/v1/acting-for-tokens", json={"email": member.email}, headers=service(None, next(iter(member.teams)))
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "tenant_required", r.text
    r = await platform.internal.post(
        "/v1/acting-for-tokens", json={"email": member.email}, headers=service(member.tenant_id)
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "tenant_required", r.text
