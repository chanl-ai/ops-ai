"""A workflow's working copy, by failure mode: a save makes a version; two people's saves overwrite each other; a copy
with an error check becomes a version; a change of step positions alone asks for a review; a restored older version
cannot be published and loses the restore; a version saved outside the editor is written over by the editor's copy.
Each goes through the routes the editor calls, on the PostgreSQL test database."""

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
    # The editor sends the definition as it holds it, without the defaults the stored version fills in.
    moved = basic()
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


async def test_a_restored_older_version_publishes_as_a_new_live_version(client: AsyncClient) -> None:
    view = await _published(client)
    first = view["definition"]
    second = (await _save(client, basic() | {"name": "Refund check v2"}, view["saveBase"])).json()["data"]
    made = await client.post(f"{WF}/versions", json={"baseVersion": 1, "baseDigest": second["saveBase"]["digest"]})
    assert made.status_code == 201, made.text
    assert (await client.post(f"{WF}/publish-requests", json={"note": "v2"})).status_code == 201
    on_two = (await client.get(WF)).json()["data"]
    assert on_two["liveVersion"] == 2
    restored = (await _save(client, first, on_two["saveBase"])).json()["data"]["saveBase"]
    # The editor publishes the copy in one call: the version is made and its request opened together.
    body = {"baseVersion": 2, "baseDigest": restored["digest"], "note": "roll back"}
    live = await client.post(f"{WF}/publish-requests", json=body)
    assert live.status_code == 201, live.text
    after = (await client.get(WF)).json()["data"]
    assert after["liveVersion"] == 3 and after["definition"]["name"] == first["name"]
    assert after["workingCopy"] is None


async def test_a_save_on_a_copy_older_than_a_version_saved_outside_the_editor_is_refused(client: AsyncClient) -> None:
    view = await _published(client)
    copy_base = (await _save(client, basic() | {"name": "Editor change"}, view["saveBase"])).json()["data"]["saveBase"]
    # Someone pushes version 2 through the API (the SDK's and CLI's `workflows save`) while the copy is open.
    pushed = await client.post("/v1/workflows/definitions", json={"definition": basic() | {"name": "CLI change"}})
    assert pushed.status_code == 201 and pushed.json()["data"]["version"] == 2, pushed.text
    refused = await _save(client, basic() | {"name": "Editor change, later"}, copy_base)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "stale_base" and refused.json()["error"]["details"]["version"] == 2
    made = await client.post(f"{WF}/versions", json={"baseVersion": 1, "baseDigest": copy_base["digest"]})
    assert made.status_code == 409 and made.json()["error"]["code"] == "stale_base", made.text
    # Read again, the editor opens on version 2 and its next save is kept.
    reread = (await client.get(WF)).json()["data"]
    assert reread["saveBase"]["version"] == 2 and reread["workingCopy"] is None
    # The editor's unpublished change is kept and shown beside who saved the newer version and when, never hidden.
    kept = reread["outdatedCopy"]
    assert kept["definition"]["name"] == "Editor change" and kept["baseVersion"] == 1, kept
    newer = pushed.json()["data"]
    assert (kept["newerVersion"], kept["newerBy"]) == (2, reread["versions"][-1]["createdBy"]), kept
    assert kept["newerAt"] == reread["versions"][-1]["createdAt"] and newer["version"] == 2
    assert (await _save(client, basic() | {"name": "Editor change on v2"}, reread["saveBase"])).status_code == 200
