"""The public surface, swept from the app's own OpenAPI document so a new route cannot slip past: every operation
but the named public ones is 401 with no credentials (I3); the internal app is 401 without the service token (I8);
no request body accepts unknown fields or names a tenant or team, and no path parameter names one (I1, I5)."""

from __future__ import annotations

import re
from typing import Any

from .conftest import Platform

PUBLIC = {
    ("GET", "/v1/health"),
    ("GET", "/.well-known/jwks.json"),
    ("POST", "/v1/auth/sign-in"),
    ("POST", "/v1/auth/refresh"),
    ("GET", "/v1/invites/{token}"),
    ("POST", "/v1/invites/{token}/accept"),
}
SAMPLE = {"token": "inv_aaaaaaaaaaaa", "key_id": "key_aaaaaaaa"}


def operations(doc: dict[str, Any]) -> list[tuple[str, str]]:
    return [(m.upper(), p) for p, ops in doc["paths"].items() for m in ops]


def concrete(path: str) -> str:
    return re.sub(r"\{([^}]+)\}", lambda m: SAMPLE.get(m.group(1), "x"), path)


async def test_every_non_public_route_is_401_without_credentials(platform: Platform) -> None:
    doc = platform.public_app.openapi()
    swept = [op for op in operations(doc) if op not in PUBLIC]
    assert len(swept) >= 10
    for method, path in swept:
        r = await platform.public.request(method, concrete(path), json={})
        assert r.status_code == 401, (method, path, r.status_code)


async def test_every_internal_route_needs_the_service_token(platform: Platform) -> None:
    doc = platform.internal_app.openapi()
    for method, path in operations(doc):
        r = await platform.internal.request(method, concrete(path), json={})
        assert r.status_code == 401, (method, path)


def bodies(doc: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    schemas = doc["components"]["schemas"]
    found: list[tuple[str, dict[str, Any]]] = []
    for path, ops in doc["paths"].items():
        for op in ops.values():
            ref = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {}).get("$ref")
            if ref:
                found.append((f"{op['operationId']} {path}", schemas[ref.rsplit("/", 1)[1]]))
    return found


async def test_no_request_names_a_tenant_or_team_or_accepts_unknown_fields(platform: Platform) -> None:
    for app in (platform.public_app, platform.internal_app):
        doc = app.openapi()
        for name, schema in bodies(doc):
            assert schema.get("additionalProperties") is False, name
            assert not {"tenantId", "teamId", "tenant_id", "team_id"} & set(schema.get("properties", {})), name
        for path in doc["paths"]:
            assert not re.search(r"\{(tenant|team)", str(path)), path
