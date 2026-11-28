"""Who changes model aliases, by failure mode: an owner-only rule outside the roles matrix refuses the account admin the
matrix allows; or someone the matrix does not allow (`settings.manage`, as for provider connections) re-points every
agent of the account onto another model."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest

from ops_identity.fastapi import current_principal, current_tenant_caller
from ops_models.app import create_models_app
from ops_service_kit.contract import response_checker

from .conftest import Models
from .test_provider_keys import people


@pytest.fixture
async def client(models: Models) -> AsyncIterator[httpx.AsyncClient]:
    app = create_models_app(models.engine)
    # The seeded account, whose scripted connection the alias names.
    person = people("local")
    app.dependency_overrides[current_principal] = person
    app.dependency_overrides[current_tenant_caller] = person
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://models", event_hooks=hooks
    ) as c:
        yield c


async def test_the_roles_matrix_decides_who_creates_or_versions_an_alias(client: httpx.AsyncClient) -> None:
    name = f"fast-{uuid4().hex[:6]}"
    version = {"providerId": "prov_scripted", "modelId": "m-1", "clearedSensitivity": "internal"}

    # An account admin (Admin of the Security team holds settings.manage) creates and re-points one, not being Owner.
    made = await client.post("/v1/models/aliases", json={"name": name, **version})
    assert made.status_code == 201, made.text
    edit = await client.post(f"/v1/models/aliases/{name}/versions", json={**version, "modelId": "m-2"})
    assert edit.status_code == 201, edit.text

    # A viewer of the Security team lacks the cell: refused as for provider connections, whatever team it names.
    viewer = {"X-Role": "viewer"}
    refused = await client.post("/v1/models/aliases", json={"name": f"{name}-v", **version}, headers=viewer)
    versioned = await client.post(f"/v1/models/aliases/{name}/versions", json=version, headers=viewer)
    assert (refused.status_code, versioned.status_code) == (403, 403), (refused.text, versioned.text)
    assert {refused.json()["error"]["code"], versioned.json()["error"]["code"]} == {"admin_only"}
    listed = await client.get(f"/v1/models/aliases/{name}/versions")
    assert [v["version"] for v in listed.json()["data"]["data"]] == [1, 2], listed.text
