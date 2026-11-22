"""A workflow's working copy, by failure mode: a save makes a version; two people's saves overwrite each other; a copy
with an error check becomes a version; a change of step positions alone asks for a review; a restored older version
cannot be published and loses the restore; a version saved outside the editor is written over by the editor's copy.
Each goes through the routes the editor calls, on the PostgreSQL test database."""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient

from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, empty_engine, started

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
    broken = _broken()
    broken["nodes"][1]["parameters"]["values"] = 6
    saved = await _save(client, broken, view["saveBase"])
    assert saved.status_code == 200, saved.text
    checks = saved.json()["data"]["workingCopy"]["checks"]
    assert ("ghost", "unknown_type") in {(c["node"], c["code"]) for c in checks}
    # A setting's error reads as the step's form names it, not as the schema validator words it.
    assert {(c["node"], c["message"]) for c in checks if c["code"] == "invalid_parameter"} == {
        ("fields", "Fields must be a group of named values.")
    }, checks
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


async def _publish(client: AsyncClient, base: dict[str, Any]) -> Any:
    """The editor's one-call publish of the working copy saved on `base`."""
    body = {"baseVersion": base["version"], "baseDigest": base["digest"], "note": "publish"}
    return await client.post(f"{WF}/publish-requests", json=body)


async def test_a_copy_with_an_error_makes_no_version_and_a_clean_one_does(client: AsyncClient) -> None:
    view = await _published(client)
    broken = (await _save(client, _broken(), view["saveBase"])).json()["data"]
    refused = await _publish(client, broken["saveBase"])
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "definition_checks"
    assert [v["version"] for v in (await client.get(WF)).json()["data"]["versions"]] == [1]
    fixed = (await _save(client, basic() | {"name": "Refund check v2"}, broken["saveBase"])).json()["data"]
    made = await _publish(client, fixed["saveBase"])
    assert made.status_code == 201, made.text
    after = (await client.get(WF)).json()["data"]
    assert [v["version"] for v in after["versions"]] == [1, 2]
    assert after["workingCopy"] is None and after["saveBase"]["version"] == 2


async def _refused_and_kept(client: AsyncClient, base: dict[str, Any], code: str, versions: list[int]) -> None:
    """The preview lists `code`, and the publish refuses with it, making no version and keeping the copy."""
    preview = (await client.get(f"{WF}/publish-preview")).json()["data"]
    assert code in [b["code"] for b in preview["blockers"]], preview["blockers"]
    refused = await _publish(client, base)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == code, refused.text
    after = (await client.get(WF)).json()["data"]
    assert [v["version"] for v in after["versions"]] == versions
    assert after["workingCopy"] is not None and after["saveBase"] == base


class _PolicyDown:
    """platform-service failing in a way the policy reader does not turn into PolicyUnread."""

    async def value(self, key: str) -> Any:
        raise RuntimeError(f"{key}: connection reset")


async def test_a_policy_read_that_fails_leaves_versions_and_copy_and_the_publish_can_be_sent_again(
    graph_models: FakeGraphModels, database_url: str
) -> None:
    settings = Settings(database_url=database_url, seed_dir=SEED)
    async with empty_engine(database_url) as engine, started(engine, settings, graph_models) as (app, client):
        view = await _published(client)
        base = (await _save(client, basic() | {"name": "Refund check v2"}, view["saveBase"])).json()["data"]["saveBase"]
        rt = app.state.runtime
        working, rt.policies = rt.policies, _PolicyDown()
        failed = await _publish(client, base)
        assert failed.status_code == 500, failed.text
        rt.policies = working
        after = (await client.get(WF)).json()["data"]
        assert [v["version"] for v in after["versions"]] == [1]
        assert after["workingCopy"] is not None and after["saveBase"] == base
        again = await _publish(client, base)
        assert again.status_code == 201, again.text
        assert [v["version"] for v in (await client.get(WF)).json()["data"]["versions"]] == [1, 2]


async def test_a_document_type_that_cannot_be_pinned_is_listed_and_refused_before_a_version_is_made(
    client: AsyncClient,
) -> None:
    view = await _published(client)
    named = basic()
    # A document type named without a version is pinned to its newest when the version is made; this service has no
    # documents-service to read it from.
    read = {"file": "$.input.fileId", "documentType": {"id": "supplier_invoice"}}
    named["nodes"].append(
        {"id": "read", "type": "ops.ai.extract", "typeVersion": 1, "name": "Read", "parameters": read}
    )
    base = (await _save(client, named, view["saveBase"])).json()["data"]["saveBase"]
    preview = (await client.get(f"{WF}/publish-preview")).json()["data"]
    assert "document_type_unreachable" in [b["code"] for b in preview["blockers"]], preview["blockers"]
    refused = await _publish(client, base)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "document_type_unreachable", refused.text
    after = (await client.get(WF)).json()["data"]
    assert [v["version"] for v in after["versions"]] == [1]
    assert after["workingCopy"] is not None and after["saveBase"] == base


async def test_a_tool_step_the_team_lacks_is_listed_with_its_step_and_refused(client: AsyncClient) -> None:
    view = await _published(client)
    named = basic()
    lookup = next(n for n in named["nodes"] if n["id"] == "lookup")
    lookup["parameters"]["operation"] = "wire_offshore_funds"
    base = (await _save(client, named, view["saveBase"])).json()["data"]["saveBase"]
    preview = (await client.get(f"{WF}/publish-preview")).json()["data"]
    missing = [b for b in preview["blockers"] if b["code"] == "tool_not_available"]
    assert {"node", "field", "level", "code", "message"} <= set(missing[0]), "the shape agent and skill checks return"
    assert [(b["node"], b["field"], b["level"]) for b in missing] == [("lookup", "operation", "error")], preview
    refused = await _publish(client, base)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "tool_not_available", refused.text


@pytest.fixture
async def reviewed(graph_models: FakeGraphModels, database_url: str) -> AsyncIterator[AsyncClient]:
    """The app with the dev auto-approve off, so a publish waits in Reviews."""
    settings = Settings(database_url=database_url, seed_dir=SEED, registry_auto_approve=False)
    async with empty_engine(database_url) as engine, started(engine, settings, graph_models, checked=True) as (_, c):
        yield c


async def test_a_publish_while_a_review_is_open_is_listed_and_refused_before_a_version_is_made(
    reviewed: AsyncClient,
) -> None:
    client = reviewed
    made = await client.post("/v1/workflows/definitions", json={"yaml": BASIC.read_text()})
    assert made.status_code == 201, made.text
    sent = await client.post(f"{WF}/publish-requests", json={"note": "first"})
    assert sent.status_code == 201 and sent.json()["data"]["status"] == "pending", sent.text
    opened = (await client.get(WF)).json()["data"]["saveBase"]
    base = (await _save(client, basic() | {"name": "Refund check, while waiting"}, opened)).json()["data"]["saveBase"]
    await _refused_and_kept(client, base, "review_open", [1])


async def test_a_copy_equal_to_the_live_version_is_listed_and_refused_with_the_copy_kept(client: AsyncClient) -> None:
    view = await _published(client)
    # The editor's copy after a change was made and taken back: the live version again.
    base = (await _save(client, basic(), view["saveBase"])).json()["data"]["saveBase"]
    await _refused_and_kept(client, base, "not_a_draft", [1])


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
    assert (await _publish(client, second["saveBase"])).status_code == 201
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
    made = await _publish(client, copy_base)
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
    # Another builder's tab opened on the copy before version 2 is told about version 2, as its author's is.
    other = {"X-Dev-User": "maya.chen@harborpine.example"}
    late = {"definition": basic(), "baseVersion": 1, "baseDigest": copy_base["digest"]}
    told = await client.put(f"{WF}/working-copy", json=late, headers=other)
    assert told.status_code == 409 and told.json()["error"]["details"]["version"] == 2, told.text
    # Another builder starting from version 2 is refused while the copy is someone else's, naming whose it is.
    on_two = {
        "definition": basic() | {"name": "Maya's change"},
        "baseVersion": 2,
        "baseDigest": reread["saveBase"]["digest"],
    }
    refused = await client.put(f"{WF}/working-copy", json=on_two, headers=other)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "stale_base", refused.text
    assert refused.json()["error"]["details"]["savedBy"] == kept["updatedBy"], refused.text
    assert (await client.get(WF)).json()["data"]["outdatedCopy"]["definition"]["name"] == "Editor change"
    # A digest that is not the kept copy's names no copy, so the copy stays.
    wrong = await client.put(f"{WF}/working-copy", json=on_two | {"replacesDigest": "0" * 64}, headers=other)
    assert wrong.status_code == 409 and wrong.json()["error"]["code"] == "stale_base", wrong.text
    assert (await client.get(WF)).json()["data"]["outdatedCopy"]["definition"]["name"] == "Editor change"
    # A save that names the copy it replaces is the builder choosing to start from version 2.
    replacing = on_two | {"replacesDigest": kept["digest"]}
    replaced = await client.put(f"{WF}/working-copy", json=replacing, headers=other)
    assert replaced.status_code == 200 and replaced.json()["data"]["saveBase"]["version"] == 2, replaced.text
