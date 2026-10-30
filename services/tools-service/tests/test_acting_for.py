"""Whom a tool call acts for (c-558), by failure mode: a person's session token stands in for an acting-for token, a
token minted for another service or another team is taken, a dev stack's self-signed token passes on a platform stack,
the call log drops the person, and a code run's own calls forget whom the run acted for.

The app runs as on a platform stack: people's tokens verify against a published key set of this test's own."""

from __future__ import annotations

from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import ActingForPerson, Auth, Identity, dev_service_signer, mint_service_token
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import Ed25519Signer, HmacSigner, mint
from ops_service_kit.settings import Settings
from ops_tools.code_runs import CodeExecutor, run_acting_for, run_claims
from ops_tools.store.calls import gateway_calls
from ops_tools.tools import ToolCaller

from .conftest import build_app, no_api_keys, opa_client

PEOPLE = Ed25519Signer.generate("platform-test-1")
TEAM = "team_ops"


async def published() -> dict[str, Any]:
    return {"keys": [PEOPLE.verifier("tools").public_jwk()]}


def platform_auth() -> Auth:
    services = Auth.for_dev(Settings(), audience="tools", name="dev", email="dev@bank.test").services
    return Auth(Identity(audience="tools", jwks=published, introspect=no_api_keys, services=services), services)


def service(tenant: str, team: str = TEAM, name: str = "agents") -> dict[str, str]:
    token = mint_service_token(dev_service_signer(), service=name, audience="tools", tenant_id=tenant, team_id=team)
    return {"Authorization": f"Bearer {token}"}


def acting(
    tenant: str,
    *,
    kind: str = "acting_for",
    act: str = "service:agents",
    team: str = TEAM,
    signer: Ed25519Signer = PEOPLE,
) -> str:
    claims = {
        "sub": "usr_james",
        "email": "j.richardson@bank.test",
        "name": "James Richardson",
        "tenant_id": tenant,
        "team_id": team,
        "kind": kind,
        "act": {"sub": act},
        "aud": "tools",
    }
    return mint(claims, signer, ttl_s=TEST_TOKEN_TTL_S)


async def call(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, token: str | None, key: str, *, auth: Auth | None = None
) -> httpx.Response:
    app = build_app(engine, seed, tenant, opa=opa_client(), dev=False, auth=auth or platform_auth())
    headers = service(tenant) | ({"X-Acting-For": token} if token else {})
    body = {
        "tool": "no_such_tool",
        "input": {},
        "key": f"{key}-{tenant}",
        "runContext": {"act": "workflow:t", "environment": "test"},
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c:
        return await c.post("/v1/calls", json=body, headers=headers)


async def logged(engine: AsyncEngine, tenant: str, key: str) -> str | None:
    """The call's log row by its key, unique to this test's tenant: the test database keeps earlier runs' rows."""
    found = gateway_calls.c.idempotency_key == f"{key}-{tenant}"
    async with engine.connect() as c:
        return (await c.execute(sa.select(gateway_calls.c.acting_for).where(found))).scalar_one_or_none()


async def test_the_call_log_names_the_person_a_verified_token_acts_for(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str
) -> None:
    r = await call(engine, seed, tenant, acting(tenant), "af-ok")
    assert "acting_for_refused" not in r.text, r.text
    assert await logged(engine, tenant, "af-ok") == "j.richardson@bank.test"
    await call(engine, seed, tenant, None, "af-none")
    assert await logged(engine, tenant, "af-none") is None


async def test_a_session_token_or_another_services_or_teams_token_is_refused(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str
) -> None:
    for key, token in (
        ("af-session", acting(tenant, kind="person")),
        ("af-kb", acting(tenant, act="service:kb")),
        ("af-team", acting(tenant, team="team_fraud")),
        ("af-tenant", acting("ten_elsewhere")),
    ):
        r = await call(engine, seed, tenant, token, key)
        assert r.status_code == 403 and r.json()["error"]["code"] == "acting_for_refused", (key, r.text)
        assert await logged(engine, tenant, key) is None


async def test_a_token_a_service_signed_for_itself_passes_in_dev_only(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str
) -> None:
    self_signed = acting(tenant, signer=dev_service_signer())
    refused = await call(engine, seed, tenant, self_signed, "af-self-platform")
    assert refused.json()["error"]["code"] == "acting_for_refused", refused.text
    dev = Auth.for_dev(Settings(), audience="tools", name="dev", email="dev@bank.test", tenant_id=tenant)
    taken = await call(engine, seed, tenant, self_signed, "af-self-dev", auth=dev)
    assert "acting_for_refused" not in taken.text, taken.text
    assert await logged(engine, tenant, "af-self-dev") == "j.richardson@bank.test"


def test_a_code_runs_call_token_carries_whom_the_run_acts_for() -> None:
    signer = HmacSigner.derived("test-secret", "code-run")
    code = CodeExecutor(None, signer)
    person = ActingForPerson(sub="usr_james", email="j.richardson@bank.test", name="James", team_id=TEAM)
    caller = ToolCaller(tenant_id="ten_a", team_id=TEAM, sub="service:agents", kind="service", acting_for=person)
    op = {"name": "fn", "access": "read"}
    token = code.token(op, {"source": "x"}, caller, "k1", "test", module_team=TEAM)
    assert run_acting_for(run_claims(token, signer)) == person
    nobody = code.token(
        op, {"source": "x"}, ToolCaller("ten_a", TEAM, "service:agents", "service"), "k2", "test", module_team=TEAM
    )
    assert run_acting_for(run_claims(nobody, signer)) is None
