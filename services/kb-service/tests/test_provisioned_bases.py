"""Knowledge bases carry a template id and a protection level (c-180), by failure mode: a provisioned base not found
again by its template id, a person setting either field, a person changing a system base, a managed base losing its
template id on an edit, and a base from before reading as protected."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, dev_service_signer, mint_service_token, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_kb.agents import StaticAgents
from ops_kb.app import create_kb_app
from ops_kb.files import KnowledgeFiles
from ops_policy import mint
from ops_service_kit.settings import Settings

from .test_ownership import PLATFORM

SCOPES = ["knowledge:view", "knowledge:create", "knowledge:edit", "knowledge:delete", "knowledge:provision"]


def provisioner(tenant: str, scopes: list[str] = SCOPES) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="platform", audience="kb", tenant_id=tenant, scopes=scopes, team_id="team_ops"
    )
    return {"Authorization": f"Bearer {token}"}


async def _jwks() -> dict[str, Any]:
    return {"keys": [PLATFORM.public_jwk()]}


async def _no_keys(_key: str) -> dict[str, Any] | None:
    return None


def person(tenant: str, email: str, role: str) -> dict[str, str]:
    """A person in team_ops as platform-service signs them in; an admin also holds knowledge.manage (c-180)."""
    claims = {
        "sub": f"usr_{email.split('@', maxsplit=1)[0]}",
        "email": email,
        "name": email,
        "kind": "person",
        "aud": ["kb"],
        "tenant_id": tenant,
        "team_ids": ["team_ops"],
        "roles": {"team_ops": role},
        "auth_method": "session",
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": "team_ops"}


@pytest.fixture
async def kb(engine: AsyncEngine, tenant: str) -> AsyncIterator[httpx.AsyncClient]:
    """Requests go as James, a builder, unless a test sends other headers."""
    settings = Settings(service_scopes={"platform": SCOPES})
    services = ServiceAuth(audience="kb", verifiers=service_verifiers(settings, "kb"), scopes=settings.service_scopes)
    auth = Auth(Identity(audience="kb", jwks=_jwks, introspect=_no_keys, key_cache_s=0, services=services), services)
    app = create_kb_app(
        engine, auth=auth, files=KnowledgeFiles(Path(mkdtemp(prefix="kb-files-"))), agents=StaticAgents()
    )
    james = person(tenant, "james@harborpine.example", "builder")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kb", headers=james) as c:
        yield c


def _data(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


async def _provisioned(c: httpx.AsyncClient, tenant: str, protection: str) -> dict[str, Any]:
    body = {
        "name": f"Policies {protection}",
        "owner": "james@harborpine.example",
        "templateId": "banking/policies",
        "protection": protection,
    }
    return _data(await c.post("/v1/knowledge-bases", json=body, headers=provisioner(tenant)), 201)


async def test_a_provisioned_base_is_found_again_by_its_template_id(kb: httpx.AsyncClient, tenant: str) -> None:
    made = await _provisioned(kb, tenant, "managed")
    _data(await kb.post("/v1/knowledge-bases", json={"name": "Team notes", "owner": "james@harborpine.example"}), 201)
    found = _data(await kb.get("/v1/knowledge-bases", params={"templateId": "banking/policies"}))
    assert [b["id"] for b in found["data"]] == [made["id"]]
    assert (made["templateId"], made["protection"]) == ("banking/policies", "managed")


async def test_only_the_provisioner_sets_template_fields(kb: httpx.AsyncClient, tenant: str) -> None:
    body = {"name": "Mine", "owner": "platform", "templateId": "banking/policies"}
    refused = await kb.post("/v1/knowledge-bases", json=body)
    assert (refused.status_code, refused.json()["error"]["code"]) == (403, "provisioner_only"), refused.text
    unscoped = await kb.post(
        "/v1/knowledge-bases", json=body, headers=provisioner(tenant, ["knowledge:view", "knowledge:edit"])
    )
    assert unscoped.status_code == 403, unscoped.text


async def test_a_system_base_is_changed_by_an_admin_or_the_provisioner_not_a_builder(
    kb: httpx.AsyncClient, tenant: str
) -> None:
    made = await _provisioned(kb, tenant, "system")
    edit = await kb.patch(f"/v1/knowledge-bases/{made['id']}", json={"description": "Changed"})
    assert (edit.status_code, edit.json()["error"]["code"]) == (403, "system_record"), edit.text
    gone = await kb.delete(f"/v1/knowledge-bases/{made['id']}")
    assert (gone.status_code, gone.json()["error"]["code"]) == (403, "system_record"), gone.text
    _data(
        await kb.patch(f"/v1/knowledge-bases/{made['id']}", json={"description": "Synced"}, headers=provisioner(tenant))
    )
    priya = person(tenant, "priya@harborpine.example", "admin")
    _data(await kb.patch(f"/v1/knowledge-bases/{made['id']}", json={"description": "Admin's"}, headers=priya))


async def test_a_managed_base_is_edited_and_keeps_its_template(kb: httpx.AsyncClient, tenant: str) -> None:
    made = await _provisioned(kb, tenant, "managed")
    after = _data(await kb.patch(f"/v1/knowledge-bases/{made['id']}", json={"description": "Ours"}))
    assert (after["description"], after["templateId"], after["protection"]) == ("Ours", "banking/policies", "managed")


async def test_a_base_made_without_a_template_reads_as_neither(kb: httpx.AsyncClient) -> None:
    own = _data(await kb.post("/v1/knowledge-bases", json={"name": "Plain", "owner": "james@harborpine.example"}), 201)
    assert (own["templateId"], own["protection"]) == (None, None)
