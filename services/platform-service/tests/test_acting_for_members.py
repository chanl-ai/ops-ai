"""The members routes called by tools-service for a person (the assistant's invite_people), by failure mode: the call
acts beyond the person's own rights (a viewer invites), a proof that is missing, forged, for another service or for
another team is taken, and the invite names the service instead of the person who asked."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import sqlalchemy as sa

from ops_identity import ServiceAuth, mint_service_token
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_platform.api.app import create_internal_app, create_public_app
from ops_platform.store.tables import audit_entries, members
from ops_policy import Ed25519Signer, mint, verify

from .conftest import CALLER, DEMO_PASSWORD, Person, Platform, seed_tx

TOOLS = Ed25519Signer.generate("svc-tools-1")
SERVICES = ServiceAuth(
    audience="platform",
    verifiers={CALLER.kid: (CALLER.verifier("platform"), "agents"), TOOLS.kid: (TOOLS.verifier("platform"), "tools")},
    tenant_scoped=False,
    scopes={},
)


class Rig:
    def __init__(self, platform: Platform, public: httpx.AsyncClient, internal: httpx.AsyncClient) -> None:
        self.platform, self.public, self.internal = platform, public, internal

    async def proof(self, p: Person, team: str, *, by: Ed25519Signer = TOOLS, audience: str = "platform") -> str:
        service = "tools" if by is TOOLS else "agents"
        r = await self.internal.post(
            "/v1/acting-for-tokens",
            json={"email": p.email, "audience": audience},
            headers=svc(by, service, p.tenant_id, team),
        )
        assert r.status_code == 200, r.text
        return r.json()["data"]["token"]

    async def invite(self, p: Person, team: str, proof: str | None, email: str) -> httpx.Response:
        h = svc(TOOLS, "tools", p.tenant_id, team)
        if proof is not None:
            h["X-Acting-For"] = proof
        return await self.public.post(
            "/v1/settings/members/invite", headers=h, json={"emails": [email], "role": "viewer"}
        )

    async def invited(self, tenant: str, email: str) -> list[str]:
        async with seed_tx(self.platform.engine, tenant) as c:
            rows = await c.execute(
                sa.select(members.c.id).where(members.c.tenant_id == tenant, members.c.email == email)
            )
            return [str(r[0]) for r in rows]


def svc(by: Ed25519Signer, service: str, tenant: str, team: str) -> dict[str, str]:
    token = mint_service_token(
        by, service=service, audience="platform", tenant_id=tenant, team_id=team, ttl_s=TEST_TOKEN_TTL_S
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def rig(platform: Platform) -> AsyncIterator[Rig]:
    public = create_public_app(
        platform.store, platform.signer, demo_password=DEMO_PASSWORD, audiences=["platform"], services=SERVICES
    )
    internal = create_internal_app(platform.store, services=SERVICES, signer=platform.signer)
    async with (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=public), base_url="http://platform") as pub,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=internal), base_url="http://internal") as inner,
    ):
        yield Rig(platform, pub, inner)


def team_of(p: Person, role: str) -> str:
    return next(t for t, r in p.teams.items() if r == role)


async def test_an_admins_invite_through_tools_names_the_admin_and_the_proof_holds_one_teams_role(rig: Rig) -> None:
    admin = await rig.platform.person(roles=("admin", "viewer"))
    team = team_of(admin, "admin")
    proof = await rig.proof(admin, team)
    claims = verify(proof, rig.platform.signer.verifier("platform"))
    # Only the role of the call's team travels, so a service deciding by it never sees the person's other teams.
    assert claims["roles"] == {team: "admin"} and claims["act"] == {"sub": "service:tools"}, claims
    r = await rig.invite(admin, team, proof, "sam@bank.test")
    assert r.status_code == 200, r.text
    async with seed_tx(rig.platform.engine, admin.tenant_id) as c:
        actor = (
            await c.execute(
                sa.select(audit_entries.c.actor).where(
                    audit_entries.c.tenant_id == admin.tenant_id, audit_entries.c.action == "member.invite"
                )
            )
        ).scalar()
    assert actor == admin.user_id


async def test_a_viewers_invite_through_tools_is_refused_and_makes_nothing(rig: Rig) -> None:
    viewer = await rig.platform.person(roles=("viewer",))
    team = team_of(viewer, "viewer")
    r = await rig.invite(viewer, team, await rig.proof(viewer, team), "sam@bank.test")
    assert r.status_code == 403 and r.json()["error"]["code"] == "admin_required", r.text
    assert await rig.invited(viewer.tenant_id, "sam@bank.test") == []


async def test_a_missing_forged_or_other_service_proof_is_refused(rig: Rig) -> None:
    admin = await rig.platform.person(roles=("admin",))
    team = team_of(admin, "admin")
    real = verify(await rig.proof(admin, team), rig.platform.signer.verifier("platform"))
    # The same claims signed by tools-service's own key: only platform-service's key vouches for a person.
    forged = mint({k: v for k, v in real.items() if k not in ("iat", "exp")}, TOOLS, ttl_s=60)
    # A proof minted for agents-service's calls to tools-service, replayed here.
    for_tools = await rig.proof(admin, team, by=CALLER, audience="tools")
    for proof in (None, forged, for_tools):
        r = await rig.invite(admin, team, proof, "sam@bank.test")
        assert r.status_code == 403 and r.json()["error"]["code"] == "acting_for_refused", r.text
    # Agents-service may not ask for a proof to send here at all.
    r = await rig.internal.post(
        "/v1/acting-for-tokens",
        json={"email": admin.email, "audience": "platform"},
        headers=svc(CALLER, "agents", admin.tenant_id, team),
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "acting_for_refused", r.text
    assert await rig.invited(admin.tenant_id, "sam@bank.test") == []


async def test_a_proof_for_one_team_is_refused_on_a_call_in_another(rig: Rig) -> None:
    admin = await rig.platform.person(roles=("admin", "admin"))
    first, second = list(admin.teams)
    r = await rig.invite(admin, second, await rig.proof(admin, first), "sam@bank.test")
    assert r.status_code == 403 and r.json()["error"]["code"] == "acting_for_refused", r.text
    assert await rig.invited(admin.tenant_id, "sam@bank.test") == []
