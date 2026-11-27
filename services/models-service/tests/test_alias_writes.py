"""Who changes model aliases, by failure mode: an alias is install-wide (one install serves one account), so a
workspace's Admin, even of its Security team, creating or re-pointing one would change every team's model. Only the
install admin (`install.manage`, held by Owner) writes them; reading them is unchanged."""

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
    person = people(f"t_{uuid4().hex[:8]}")
    app.dependency_overrides[current_principal] = person
    app.dependency_overrides[current_tenant_caller] = person
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://models", event_hooks=hooks
    ) as c:
        yield c


async def test_only_the_install_admin_creates_or_versions_an_alias(client: httpx.AsyncClient) -> None:
    name = f"fast-{uuid4().hex[:6]}"
    version = {"providerId": "prov_scripted", "modelId": "m-1", "clearedSensitivity": "internal"}

    # The account admin (Admin of the Security team) is refused; the same person as Owner is not.
    refused = await client.post("/v1/models/aliases", json={"name": name, **version})
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "install_admin_only"
    made = await client.post("/v1/models/aliases", json={"name": name, **version}, headers={"X-Owner": "yes"})
    assert made.status_code == 201, made.text

    edit = await client.post(f"/v1/models/aliases/{name}/versions", json={**version, "modelId": "m-2"})
    assert edit.status_code == 403, edit.text
    assert edit.json()["error"]["code"] == "install_admin_only"
    # Reading stays with whoever read before: the account admin still lists the alias at its first version.
    listed = await client.get(f"/v1/models/aliases/{name}/versions")
    assert [v["version"] for v in listed.json()["data"]["data"]] == [1], listed.text
