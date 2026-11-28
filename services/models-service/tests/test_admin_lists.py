"""The admin lists (provider connections, aliases, an alias's versions, model keys) by failure mode: a row missing or
out of order, a retired alias version listed as serving, a page that repeats or skips a row, `ids` refused on a table
keyed by more than one column, and an alias's versions answered 404 when it exists but nothing matches."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx

from .conftest import PRICE, SERVICE, Models


async def every_row(client: httpx.AsyncClient, path: str, **params: Any) -> list[dict[str, Any]]:
    """Every row of a list, page after page at the largest page size, in the order it is answered."""
    found: list[dict[str, Any]] = []
    page = 1
    while True:
        r = await client.get(path, headers=SERVICE, params={**params, "page": page, "pageSize": 50})
        assert r.status_code == 200, r.text
        found += r.json()["data"]["data"]
        if not r.json()["data"]["pagination"]["hasNext"]:
            return found
        page += 1


def _version(**extra: str) -> dict[str, str]:
    return {"providerId": "prov_scripted", "modelId": "m-1", "clearedSensitivity": "internal", **PRICE, **extra}


async def test_provider_connections_are_listed_by_name(models: Models) -> None:
    prefix = f"lp-{uuid4().hex[:6]}"
    made: dict[str, str] = {}
    for suffix in ("c", "a", "b"):
        body = {"name": f"{prefix}-{suffix}", "type": "openai-compatible", "baseUrl": "http://up/v1"}
        r = await models.client.post("/v1/models/providers", json=body, headers=SERVICE)
        assert r.status_code == 201, r.text
        made[suffix] = r.json()["data"]["id"]

    listed = [p["name"] for p in await every_row(models.client, "/v1/models/providers")]

    assert [n for n in listed if n.startswith(prefix)] == [f"{prefix}-a", f"{prefix}-b", f"{prefix}-c"]
    assert listed == sorted(listed)
    # `sortBy` orders the whole list on the server, across pages, not just the page the caller holds.
    backwards = await every_row(models.client, "/v1/models/providers", sortBy="name", sortOrder="desc")
    assert [p["name"] for p in backwards if p["name"].startswith(prefix)] == [
        f"{prefix}-c",
        f"{prefix}-b",
        f"{prefix}-a",
    ]
    searched = await every_row(models.client, "/v1/models/providers", search=prefix.upper())
    assert [p["name"] for p in searched] == [f"{prefix}-a", f"{prefix}-b", f"{prefix}-c"]
    picked = await every_row(models.client, "/v1/models/providers", ids=made["b"], search="no-such-connection")
    assert [p["name"] for p in picked] == [f"{prefix}-b"]


async def test_aliases_list_each_serving_version_by_name(models: Models) -> None:
    prefix = f"la-{uuid4().hex[:6]}"
    for suffix in ("b", "c", "a"):
        r = await models.client.post("/v1/models/aliases", json=_version(name=f"{prefix}-{suffix}"), headers=SERVICE)
        assert r.status_code == 201, r.text
    await models.client.post(f"/v1/models/aliases/{prefix}-b/versions", json=_version(modelId="m-2"), headers=SERVICE)

    listed = [(a["name"], a["version"]) for a in await every_row(models.client, "/v1/models/aliases")]

    assert [row for row in listed if row[0].startswith(prefix)] == [
        (f"{prefix}-a", 1),
        (f"{prefix}-b", 2),
        (f"{prefix}-c", 1),
    ]
    assert [n for n, _ in listed] == sorted(n for n, _ in listed)
    searched = await every_row(models.client, "/v1/models/aliases", search=prefix)
    assert [a["name"] for a in searched] == [f"{prefix}-a", f"{prefix}-b", f"{prefix}-c"]
    # (name, version) keys the table, so `ids` names an alias by name.
    picked = await every_row(models.client, "/v1/models/aliases", ids=[f"{prefix}-b", f"{prefix}-c"], search="none")
    assert [(a["name"], a["version"]) for a in picked] == [(f"{prefix}-b", 2), (f"{prefix}-c", 1)]


async def test_an_aliases_versions_are_listed_oldest_first(models: Models) -> None:
    name = f"lv-{uuid4().hex[:6]}"
    await models.client.post("/v1/models/aliases", json=_version(name=name), headers=SERVICE)
    # More versions than the largest page holds, so the order is held across pages.
    for model in [f"m-{n}" for n in range(2, 53)]:
        await models.client.post(f"/v1/models/aliases/{name}/versions", json=_version(modelId=model), headers=SERVICE)

    listed = await every_row(models.client, f"/v1/models/aliases/{name}/versions")

    assert [(v["version"], v["modelId"], v["status"]) for v in listed] == [
        *[(n, f"m-{n}", "retired") for n in range(1, 52)],
        (52, "m-52", "current"),
    ]
    picked = await every_row(models.client, f"/v1/models/aliases/{name}/versions", ids=["2", "x"], search="current")
    assert [v["version"] for v in picked] == [2]
    unmatched = await models.client.get(
        f"/v1/models/aliases/{name}/versions", params={"search": "no-such-model"}, headers=SERVICE
    )
    assert (unmatched.status_code, unmatched.json()["data"]["data"]) == (200, [])
    missing = await models.client.get(f"/v1/models/aliases/{name}-none/versions", headers=SERVICE)
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "alias_not_found")


async def test_model_keys_are_listed_by_id(models: Models) -> None:
    prefix = f"purpose:lk-{uuid4().hex[:6]}"
    for suffix in ("b", "a", "c"):
        body = {"id": f"{prefix}-{suffix}", "kind": "purpose", "budget": "1", "rateLimitPerMinute": 5}
        assert (await models.client.post("/v1/models/keys", json=body, headers=SERVICE)).status_code == 201

    listed = [k["id"] for k in await every_row(models.client, "/v1/models/keys")]

    assert [k for k in listed if k.startswith(prefix)] == [f"{prefix}-a", f"{prefix}-b", f"{prefix}-c"]
    assert listed == sorted(listed)
    picked = await every_row(models.client, "/v1/models/keys", ids=f"{prefix}-c", search="no-such-key")
    assert [k["id"] for k in picked] == [f"{prefix}-c"]
    searched = await every_row(models.client, "/v1/models/keys", search=prefix)
    assert [k["id"] for k in searched] == [f"{prefix}-a", f"{prefix}-b", f"{prefix}-c"]
