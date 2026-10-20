"""Tool modules, egress entries and secrets carry a template id and a protection level (c-180), by failure mode: a
provisioned record not found again by its template id, a person setting either field, a person changing a system
record, a Security admin unable to set a system secret's value, a managed module losing its template id on an edit, and
a record from before reading as protected."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, dev_service_signer, mint_service_token, service_verifiers
from ops_service_kit.settings import Settings
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, response_checker
from .test_review_decisions import introspect, jwks, person

SCOPES = [
    "tools:view",
    "tools:create",
    "tools:edit",
    "tools:delete",
    "tools:provision",
    "secrets_egress:view",
    "secrets_egress:create",
    "secrets_egress:edit",
    "secrets_egress:delete",
    "secrets_egress:manage",
    "secrets_egress:provision",
]
HOST = "ledger.provisioned.example"
TEMPLATE = {"templateId": "banking/core", "protection": "system"}


def provisioner(tenant: str, scopes: list[str] = SCOPES) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(),
        service="platform",
        audience="tools",
        tenant_id=tenant,
        scopes=scopes,
        team_id="team_platform",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def tools(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, dict[str, str]]]]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    settings = Settings(service_scopes={"platform": SCOPES})
    services = ServiceAuth(
        audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes
    )
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0, services=services), services
    )
    app = build_app(engine, seed, tenant, auth=auth)
    people = {
        "james": person(tenant, "James Richardson", {"team_platform": "builder"}),
        "sam": person(tenant, "Sam Adeyemi", {"team_security": "admin"}),
        "ana": person(tenant, "Ana Lopez", {"team_platform": "admin"}),
    }
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        yield c, people


def _data(r: httpx.Response, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


def _refused(r: httpx.Response, code: str) -> None:
    assert (r.status_code, r.json()["error"]["code"]) == (403, code), r.text


async def _module(c: httpx.AsyncClient, tenant: str, name: str, protection: str) -> dict[str, Any]:
    body = {"displayName": name, "name": name, "type": "http", **TEMPLATE, "protection": protection}
    return _data(await c.post("/v1/tool-modules/blank", json=body, headers=provisioner(tenant)), 201)


async def test_each_provisioned_record_is_found_again_by_its_template_id(
    tools: tuple[httpx.AsyncClient, dict[str, dict[str, str]]], tenant: str
) -> None:
    c, people = tools
    made = await _module(c, tenant, "core-ledger", "managed")
    _data(
        await c.post(
            "/v1/tool-modules/blank",
            json={"displayName": "Mine", "name": "mine", "type": "http"},
            headers=people["james"],
        ),
        201,
    )
    found = _data(await c.get("/v1/tool-modules", params={"templateId": "banking/core"}, headers=people["james"]))
    assert [m["id"] for m in found["data"]] == [made["id"]]
    assert (made["templateId"], made["protection"]) == ("banking/core", "managed")

    _data(await c.post("/v1/egress/hosts", json={"value": HOST, **TEMPLATE}, headers=provisioner(tenant)), 201)
    _data(await c.post("/v1/egress/hosts", json={"value": "other.example.com"}, headers=people["sam"]), 201)
    hosts = _data(await c.get("/v1/egress/hosts", params={"templateId": "banking/core"}, headers=people["james"]))
    assert [(h["host"], h["protection"]) for h in hosts["data"]] == [(HOST, "system")]

    secret = {"name": "LEDGER_KEY", "value": "k1", **TEMPLATE}
    _data(await c.post("/v1/secrets", json=secret, headers=provisioner(tenant)), 201)
    _data(await c.post("/v1/secrets", json={"name": "TEAM_KEY", "value": "k2"}, headers=people["sam"]), 201)
    listed = _data(await c.get("/v1/secrets", params={"templateId": "banking/core", "page": 1}, headers=people["sam"]))
    assert [(s["name"], s["templateId"]) for s in listed["data"]] == [("LEDGER_KEY", "banking/core")]


async def test_only_the_provisioner_sets_template_fields(
    tools: tuple[httpx.AsyncClient, dict[str, dict[str, str]]], tenant: str
) -> None:
    c, people = tools
    blank = {"displayName": "Mine", "name": "mine", "type": "http", **TEMPLATE}
    _refused(await c.post("/v1/tool-modules/blank", json=blank, headers=people["james"]), "provisioner_only")
    mine = _data(
        await c.post(
            "/v1/tool-modules/blank", json={**blank, "templateId": None, "protection": None}, headers=people["james"]
        ),
        201,
    )
    _refused(
        await c.patch(f"/v1/tool-modules/{mine['id']}", json=TEMPLATE, headers=people["james"]), "provisioner_only"
    )
    _refused(
        await c.post("/v1/egress/hosts", json={"value": HOST, **TEMPLATE}, headers=people["sam"]), "provisioner_only"
    )
    secret = {"name": "LEDGER_KEY", "value": "k1", **TEMPLATE}
    _refused(await c.post("/v1/secrets", json=secret, headers=people["sam"]), "provisioner_only")
    no_provision = provisioner(tenant, [s for s in SCOPES if not s.endswith(":provision")])
    assert (await c.post("/v1/tool-modules/blank", json=blank, headers=no_provision)).status_code == 403


async def test_a_system_record_is_changed_by_an_admin_or_the_provisioner_not_a_builder(
    tools: tuple[httpx.AsyncClient, dict[str, dict[str, str]]], tenant: str
) -> None:
    c, people = tools
    made = await _module(c, tenant, "core-system", "system")
    url = f"/v1/tool-modules/{made['id']}"
    _refused(await c.patch(url, json={"description": "Changed"}, headers=people["james"]), "system_record")
    _refused(await c.delete(url, headers=people["james"]), "system_record")
    _data(await c.patch(url, json={"description": "Synced"}, headers=provisioner(tenant)))
    _data(await c.patch(url, json={"description": "Admin's"}, headers=people["ana"]))

    # Egress and secrets are changed by the Security admin, who also holds secrets_egress.manage.
    _data(await c.post("/v1/egress/hosts", json={"value": HOST, **TEMPLATE}, headers=provisioner(tenant)), 201)
    _data(await c.post("/v1/egress/hosts/remove", json={"value": HOST}, headers=people["sam"]))
    secret = {"name": "LEDGER_KEY", "value": "k1", **TEMPLATE}
    _data(await c.post("/v1/secrets", json=secret, headers=provisioner(tenant)), 201)
    rotated = _data(await c.post("/v1/secrets/LEDGER_KEY/rotate", json={"value": "k2"}, headers=people["sam"]))
    assert (rotated["version"], rotated["protection"]) == (2, "system")
    _data(await c.patch("/v1/secrets/LEDGER_KEY", json={"teams": ["team_platform"]}, headers=people["sam"]))
    assert (await c.delete("/v1/secrets/LEDGER_KEY", headers=people["sam"])).status_code == 204


async def test_a_managed_module_is_edited_and_keeps_its_template(
    tools: tuple[httpx.AsyncClient, dict[str, dict[str, str]]], tenant: str
) -> None:
    c, people = tools
    made = await _module(c, tenant, "core-managed", "managed")
    edited = _data(
        await c.patch(f"/v1/tool-modules/{made['id']}", json={"description": "Ours now"}, headers=people["james"])
    )
    assert (edited["description"], edited["templateId"], edited["protection"]) == (
        "Ours now",
        "banking/core",
        "managed",
    )


async def test_a_record_made_without_a_template_reads_as_neither(
    tools: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],
) -> None:
    c, people = tools
    seeded = _data(await c.get("/v1/tool-modules", headers=people["james"]))["data"]
    assert seeded and all(m["templateId"] is None and m["protection"] is None for m in seeded)
    _data(await c.post("/v1/egress/hosts", json={"value": HOST}, headers=people["sam"]), 201)
    allow = _data(await c.get("/v1/egress", headers=people["james"]))
    assert all(h["templateId"] is None and h["protection"] is None for h in allow["hosts"])
    _data(await c.post("/v1/secrets", json={"name": "TEAM_KEY", "value": "k"}, headers=people["sam"]), 201)
    assert all(s["protection"] is None for s in _data(await c.get("/v1/secrets", headers=people["sam"])))
    _data(await c.post("/v1/egress/hosts/remove", json={"value": HOST}, headers=people["sam"]))


async def test_bulk_delete_follows_can_for_a_system_module_as_a_single_delete_does(
    tools: tuple[httpx.AsyncClient, dict[str, dict[str, str]]], tenant: str
) -> None:
    """Admins do everything (owner): bulk delete skipped a system module for everyone but the provisioner, admins
    included, while a single delete let the admin through. Now both ask can() with the module's protection."""
    c, people = tools
    made = await _module(c, tenant, "core-bulk", "system")
    body = {"ids": [made["id"]]}
    builder = _data(await c.post("/v1/tool-modules/bulk-delete", json=body, headers=people["james"]))
    assert (builder["updated"], [s["id"] for s in builder["skipped"]]) == ([], [made["id"]]), builder
    admin = _data(await c.post("/v1/tool-modules/bulk-delete", json=body, headers=people["ana"]))
    assert admin["updated"] == [made["id"]], admin
