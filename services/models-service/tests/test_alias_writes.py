"""Who changes model aliases, by failure mode: an alias is install-wide (one install serves one account), so a
workspace's Admin, even of its Security team, creating or re-pointing one would change every team's model. Only the
install admin (`install.manage`, held by Owner) writes them; reading them is unchanged."""

from __future__ import annotations

import importlib.util
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from ops_identity.fastapi import current_principal, current_tenant_caller
from ops_models.app import create_models_app
from ops_models.catalog import Catalog
from ops_service_kit.contract import response_checker

from .conftest import PRICE, Models
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
    version = {"providerId": "prov_scripted", "modelId": "m-1", "clearedSensitivity": "internal", **PRICE}

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


async def test_an_alias_version_without_a_known_price_is_refused(client: httpx.AsyncClient) -> None:
    # A version priced at zero lets every budget pass, so a model the catalog does not price needs both prices given.
    owner = {"X-Owner": "yes"}
    name = f"priced-{uuid4().hex[:6]}"
    version = {"providerId": "prov_scripted", "modelId": "house-model-7", "clearedSensitivity": "internal"}
    for body, code in [
        (version, "price_required"),
        ({**version, "inputPerMillion": "2"}, "price_incomplete"),
        ({**version, "inputPerMillion": "0", "outputPerMillion": "0"}, "price_required"),
    ]:
        refused = await client.post("/v1/models/aliases", json={"name": name, **body}, headers=owner)
        assert refused.status_code == 422 and refused.json()["error"]["code"] == code, refused.text
    assert (await client.get(f"/v1/models/aliases/{name}/versions")).status_code == 404
    priced = {**version, "inputPerMillion": "2", "outputPerMillion": "8"}
    assert (await client.post("/v1/models/aliases", json={"name": name, **priced}, headers=owner)).status_code == 201
    again = await client.post(f"/v1/models/aliases/{name}/versions", json=version, headers=owner)
    assert again.status_code == 422 and again.json()["error"]["code"] == "price_required", again.text
    listed = await client.get(f"/v1/models/aliases/{name}/versions")
    assert [v["version"] for v in listed.json()["data"]["data"]] == [1], listed.text


async def test_a_model_the_catalog_lists_as_free_may_be_priced_at_zero(client: httpx.AsyncClient) -> None:
    owner = {"X-Owner": "yes"}
    google = {"name": f"g-{uuid4().hex[:6]}", "type": "google"}
    made = await client.post("/v1/models/providers", json=google, headers=owner)
    assert made.status_code == 201, made.text
    version = {"providerId": made.json()["data"]["id"], "modelId": "gemma-4-31b-it", "clearedSensitivity": "internal"}
    for i, body in enumerate([version, {**version, "inputPerMillion": "0", "outputPerMillion": "0"}]):
        name = f"gemma-{i}-{uuid4().hex[:6]}"
        r = await client.post("/v1/models/aliases", json={"name": name, **body}, headers=owner)
        assert r.status_code == 201, r.text


def test_every_still_served_model_is_in_the_catalog() -> None:
    sync = importlib.util.spec_from_file_location("sync_catalog", Path(__file__).parents[1] / "scripts/sync_catalog.py")
    assert sync is not None and sync.loader is not None
    module = importlib.util.module_from_spec(sync)
    sync.loader.exec_module(module)
    catalog = Catalog.load()
    missing = [(p, m) for p, ms in module.STILL_SERVED.items() for m in ms if catalog.model(p, m) is None]
    assert missing == []
