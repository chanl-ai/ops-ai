"""Who may change a knowledge base (c-056 T013), by failure mode: the owner locked out of their own, a tenant admin
unable to step in, and an admin of one team stepping into another team's. Knowledge is shared by the team since
2026-10-17, so a teammate changing someone else's base is allowed (test_write_roles)."""

from __future__ import annotations

from pathlib import Path
from tempfile import mkdtemp
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_kb.agents import StaticAgents
from ops_kb.app import create_kb_app
from ops_kb.files import KnowledgeFiles
from ops_policy import Ed25519Signer, mint
from ops_service_kit.settings import Settings

from .conftest import kb_client
from .test_bases_and_sources import data, source

OWNED_BY_MAYA = {"name": "Lending policies", "owner": "maya@northfieldbank.com"}


async def test_the_owner_changes_their_own(engine: AsyncEngine, tenant: str) -> None:
    async with kb_client(engine, tenant, "maya@northfieldbank.com") as maya:
        kb = data(await maya.post("/v1/knowledge-bases", json=OWNED_BY_MAYA), 201)
        src = await source(maya)
        renamed = data(await maya.patch(f"/v1/knowledge-bases/{kb['id']}", json={"name": "Lending rules"}))
        assert (renamed["name"], renamed["slug"]) == ("Lending rules", "lending_rules")
        attached = data(await maya.post(f"/v1/knowledge-bases/{kb['id']}/sources", json={"sourceIds": [src["id"]]}))
        assert [s["sourceId"] for s in attached["sources"]] == [src["id"]]
        blank = await maya.patch(f"/v1/knowledge-bases/{kb['id']}", json={"owner": " "})
        assert blank.status_code == 400, "a knowledge base always has an owner"
        assert (await maya.delete(f"/v1/knowledge-bases/{kb['id']}")).status_code == 204


async def test_a_tenant_admin_can_step_in(engine: AsyncEngine, tenant: str) -> None:
    async with kb_client(engine, tenant, "maya@northfieldbank.com") as maya:
        kb = data(await maya.post("/v1/knowledge-bases", json=OWNED_BY_MAYA), 201)
    async with kb_client(engine, tenant, "priya@northfieldbank.com", admin=True) as priya:
        moved = data(await priya.patch(f"/v1/knowledge-bases/{kb['id']}", json={"owner": "lee@northfieldbank.com"}))
        assert moved["owner"] == "lee@northfieldbank.com"


async def test_a_knowledge_base_can_be_created_under_an_id_it_already_has(engine: AsyncEngine, tenant: str) -> None:
    async with kb_client(engine, tenant) as client:
        body = {"id": "kb_people", "name": "Fraud & payments", "owner": "maya@northfieldbank.com"}
        made = data(await client.post("/v1/knowledge-bases", json=body), 201)
        assert made["id"] == "kb_people"
        again = await client.post("/v1/knowledge-bases", json={**body, "name": "Another"})
        assert again.status_code == 409, again.text
        bad = await client.post("/v1/knowledge-bases", json={**body, "id": "people"})
        assert bad.status_code == 400, bad.text


PLATFORM = Ed25519Signer.generate("platform-test")


async def _jwks() -> dict[str, Any]:
    return {"keys": [PLATFORM.public_jwk()]}


async def _no_keys(_key: str) -> dict[str, Any] | None:
    return None


def _signed_in(engine: AsyncEngine, tenant: str, email: str, team: str, roles: dict[str, str]) -> httpx.AsyncClient:
    """kb-service as platform-service would sign this person in: a token naming `team` and these per-team roles,
    verified against the platform key and read into `who()` as in production."""
    auth = Auth(
        Identity(audience="kb", jwks=_jwks, introspect=_no_keys, key_cache_s=0),
        ServiceAuth(audience="kb", verifiers=service_verifiers(Settings(), "kb")),
    )
    app = create_kb_app(
        engine, auth=auth, files=KnowledgeFiles(Path(mkdtemp(prefix="kb-files-"))), agents=StaticAgents()
    )
    claims = {
        "sub": f"usr_{email.split('@', maxsplit=1)[0]}",
        "email": email,
        "name": email,
        "kind": "person",
        "aud": ["kb"],
        "tenant_id": tenant,
        "team_ids": list(roles),
        "roles": roles,
        "auth_method": "session",
    }
    headers = {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": team}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kb", headers=headers)


async def test_an_admin_of_another_team_cannot_change_it(engine: AsyncEngine, tenant: str) -> None:
    """An admin role is held per team, so an admin of payments has no say over a knowledge base lending owns."""
    async with _signed_in(engine, tenant, "maya@northfieldbank.com", "team_lending", {"team_lending": "builder"}) as m:
        kb = data(await m.post("/v1/knowledge-bases", json=OWNED_BY_MAYA), 201)
        src = await source(m, owner="maya@northfieldbank.com")
    roles = {"team_payments": "admin", "team_lending": "viewer"}
    async with _signed_in(engine, tenant, "priya@northfieldbank.com", "team_lending", roles) as priya:
        for r, code in (
            (await priya.patch(f"/v1/knowledge-bases/{kb['id']}", json={"name": "Taken"}), "role_required"),
            (await priya.post(f"/v1/sources/{src['id']}/sync"), "role_required"),
        ):
            assert r.status_code == 403 and r.json()["error"]["code"] == code, r.text
    async with _signed_in(engine, tenant, "lee@northfieldbank.com", "team_lending", {"team_lending": "admin"}) as lee:
        assert (await lee.patch(f"/v1/knowledge-bases/{kb['id']}", json={"name": "Lending rules"})).status_code == 200
