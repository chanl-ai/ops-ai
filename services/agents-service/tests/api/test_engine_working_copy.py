"""A workflow's working copy, by failure mode: a save makes a version; two people's saves overwrite each other; a copy
with an error check becomes a version; a change of step positions alone asks for a review. Each goes through the routes
the editor calls, on the PostgreSQL test database."""

from __future__ import annotations

import copy
from typing import Any

from httpx import AsyncClient

from .test_engine_definitions import BASIC, basic

WF = "/v1/workflows/definitions/refund_check"


async def _published(client: AsyncClient) -> dict[str, Any]:
    """The basic workflow at version 1, live, as its editor reads it."""
    made = await client.post("/v1/workflows/definitions", json={"yaml": BASIC.read_text()})
    assert made.status_code == 201, made.text
    live = await client.post(f"{WF}/publish-requests", json={"note": "first"})
    assert live.status_code == 201, live.text
    return (await client.get(WF)).json()["data"]


async def _save(client: AsyncClient, definition: dict[str, Any], base: dict[str, Any]) -> Any:
    body = {"definition": definition, "baseVersion": base["version"], "baseDigest": base["digest"]}
    return await client.put(f"{WF}/working-copy", json=body)


def _broken() -> dict[str, Any]:
    d = basic()
    d["nodes"].append({"id": "ghost", "type": "ops.flow.teleport", "typeVersion": 1})
    return d


async def test_a_save_keeps_a_failing_copy_and_makes_no_version(client: AsyncClient) -> None:
    view = await _published(client)
    saved = await _save(client, _broken(), view["saveBase"])
    assert saved.status_code == 200, saved.text
    checks = saved.json()["data"]["workingCopy"]["checks"]
    assert ("ghost", "unknown_type") in {(c["node"], c["code"]) for c in checks}
    again = (await client.get(WF)).json()["data"]
    assert [v["version"] for v in again["versions"]] == [1]
    assert again["workingCopy"]["definition"]["nodes"][-1]["id"] == "ghost"
    assert again["saveBase"] == saved.json()["data"]["saveBase"]


async def test_a_save_made_on_an_older_copy_is_refused(client: AsyncClient) -> None:
    view = await _published(client)
    opened = view["saveBase"]
    first = basic() | {"name": "Refund check, first person"}
    assert (await _save(client, first, opened)).status_code == 200
    # The second person read the workflow before the first saved and saves on that copy.
    second = await _save(client, basic() | {"name": "Refund check, second person"}, opened)
    assert second.status_code == 409, second.text
    error = second.json()["error"]
    assert error["code"] == "stale_base"
    assert error["details"]["savedBy"] and error["details"]["version"] == 1
    kept = (await client.get(WF)).json()["data"]["workingCopy"]["definition"]
    assert kept["name"] == "Refund check, first person"


async def test_a_copy_with_an_error_makes_no_version_and_a_clean_one_does(client: AsyncClient) -> None:
    view = await _published(client)
    broken = (await _save(client, _broken(), view["saveBase"])).json()["data"]
    refused = await client.post(f"{WF}/versions", json={"baseVersion": 1, "baseDigest": broken["saveBase"]["digest"]})
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "definition_checks"
    assert [v["version"] for v in (await client.get(WF)).json()["data"]["versions"]] == [1]
    fixed = (await _save(client, basic() | {"name": "Refund check v2"}, broken["saveBase"])).json()["data"]
    made = await client.post(f"{WF}/versions", json={"baseVersion": 1, "baseDigest": fixed["saveBase"]["digest"]})
    assert made.status_code == 201, made.text
    after = (await client.get(WF)).json()["data"]
    assert [v["version"] for v in after["versions"]] == [1, 2]
    assert after["workingCopy"] is None and after["saveBase"]["version"] == 2


async def test_moving_steps_alone_publishes_without_a_review(client: AsyncClient) -> None:
    view = await _published(client)
    moved = copy.deepcopy(view["definition"])
    moved["nodes"][1]["position"] = {"x": 900, "y": 40}
    base = (await _save(client, moved, view["saveBase"])).json()["data"]["saveBase"]
    preview = (await client.get(f"{WF}/publish-preview")).json()["data"]
    assert preview["reviewRequired"] is False and preview["reviewReason"] == "minor_change", preview
    assert [s["id"] for s in preview["changes"]["moved"]] == ["fields"] and not preview["changes"]["changed"]
    changed = copy.deepcopy(moved)
    changed["nodes"][1]["parameters"]["values"]["amount"] = "$.input.total"
    await _save(client, changed, base)
    preview = (await client.get(f"{WF}/publish-preview")).json()["data"]
    assert preview["majorChange"] is True and preview["reviewReason"] != "minor_change", preview
