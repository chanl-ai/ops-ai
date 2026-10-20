"""Human Task types (c-288) through `/v1/task-types` and the binder, by failure mode: a builder edits a seeded type
every tenant shares, or an admin cannot; publishing a new version changes a task already pinned to the old one; a
viewer or another team's builder changes a team's type; a type the screen cannot draw is saved; a missing required
param refuses the task instead of showing its fallback; a wrong-kind param passes; a region with nothing to show is
drawn empty."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents import task_types as tt
from ops_agents.api.task_view import worded
from ops_agents.store.base import metadata
from ops_agents.store.task_types import TaskTypeStore
from ops_agents.store.tenancy import tenant_scope
from tests.engine.test_lifecycle_rights import ADMIN, BUILDER, VIEWER, person

from .role_app import ok, role_app

OTHER_TEAM = person("omar", "team_fraud", "builder")


@pytest.fixture
async def c() -> AsyncIterator[AsyncClient]:
    async with role_app(TestModel()) as client:
        yield client


async def _copy(c: AsyncClient, type_id: str = "vendor_bank_change") -> dict[str, Any]:
    body = {"id": type_id, "copyOf": {"id": "write_approval"}, "name": "Vendor bank change"}
    return ok(await c.post("/v1/task-types", json=body, headers=BUILDER), 201)


async def test_seeded_types_are_listed_and_changed_only_by_an_admin(c: AsyncClient) -> None:
    listed = ok(await c.get("/v1/task-types", headers=VIEWER))
    ids = {t["id"] for t in listed if t["origin"] == "seed"}
    assert {"generic_decision", "document_check", "write_approval", "acknowledgement", "data_entry"} <= ids
    seed = next(t for t in listed if t["id"] == "write_approval")
    record = ok(await c.get("/v1/task-types/write_approval", headers=VIEWER))["versions"][0]["record"]
    res = await c.put("/v1/task-types/write_approval/draft", json=record, headers=BUILDER)
    assert res.status_code == 403 and res.json()["error"]["code"] == "system_record", res.text
    assert seed["teamId"] is None
    # A system record as any other (register E05, tick 30): admins change it, decided by can(), not by its origin.
    ok(await c.put("/v1/task-types/write_approval/draft", json=record, headers=ADMIN))


async def test_a_published_version_never_changes_when_the_type_moves_on(c: AsyncClient) -> None:
    made = await _copy(c)
    assert (made["version"], made["publishedVersion"], made["copiedFrom"]) == (
        1,
        None,
        {"id": "write_approval", "version": 1},
    )
    ok(await c.post("/v1/task-types/vendor_bank_change/publish", json={"version": 1}, headers=BUILDER))
    v1 = made["versions"][0]["record"]
    changed = {**v1, "regions": [*reversed(v1["regions"])]}
    saved = ok(await c.put("/v1/task-types/vendor_bank_change/draft", json=changed, headers=BUILDER))
    assert (saved["version"], saved["publishedVersion"]) == (2, 1)
    ok(await c.post("/v1/task-types/vendor_bank_change/publish", json={"version": 2}, headers=BUILDER))
    versions = {
        v["version"]: v["record"]
        for v in ok(await c.get("/v1/task-types/vendor_bank_change", headers=VIEWER))["versions"]
    }
    assert versions[1]["regions"] == v1["regions"] and versions[2]["regions"] == changed["regions"]


async def test_only_the_owning_team_builder_changes_a_type(c: AsyncClient) -> None:
    refused = await c.post(
        "/v1/task-types", json={"id": "viewer_copy", "copyOf": {"id": "generic_decision"}}, headers=VIEWER
    )
    assert refused.status_code == 403, refused.text
    made = await _copy(c)
    record = made["versions"][0]["record"]
    other = await c.put("/v1/task-types/vendor_bank_change/draft", json=record, headers=OTHER_TEAM)
    assert other.status_code == 404, "another team's type is not read at all (c-407): " + other.text


async def test_a_type_the_screen_cannot_draw_is_refused(c: AsyncClient) -> None:
    body: dict[str, Any] = {
        "id": "broken_type",
        "copyOf": {"id": "generic_decision"},
        "regions": [{"region": "sidebar", "bind": {}}],
    }
    res = await c.post("/v1/task-types", json=body, headers=BUILDER)
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_task_type", res.text
    assert "regions[0]" in res.json()["error"]["message"]


def test_a_missing_param_warns_and_shows_its_fallback_and_a_wrong_kind_is_an_error() -> None:
    record = next(s for s in tt.seeds() if s["id"] == "write_approval")
    issues = tt.check_params(record, {"facts": "not a list"})
    assert {(i["field"], i["severity"]) for i in issues} == {
        ("title", "warning"),
        ("call", "warning"),
        ("facts", "error"),
    }
    bound = tt.bind(record, {"call": {"tool": "update_vendor_bank"}})
    header = next(r for r in bound["regions"] if r["region"] == "header")
    assert header["data"]["title"] == "Approve this change"
    assert bound["actions"][0]["consequence"] == "The change is made now."


def test_a_region_with_nothing_to_show_is_left_out_and_a_whole_template_keeps_its_value() -> None:
    record = next(s for s in tt.seeds() if s["id"] == "generic_decision")
    facts = [{"label": "Amount", "value": "3,250.00 CAD"}]
    bound = tt.bind(record, {"title": "Open the case?", "facts": facts})
    assert [r["region"] for r in bound["regions"]] == ["header", "facts"]
    assert bound["regions"][1]["data"]["facts"] == facts


def test_the_document_region_carries_each_fields_boxes_flat() -> None:
    """The viewer draws a read's boxes from the document region alone (opsai-worker-ui, c-289)."""
    record = next(s for s in tt.seeds() if s["id"] == "document_check")
    fields = [
        {"key": "amount", "check": True, "boxes": [{"page": 1, "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.04}]},
        {"key": "case_no", "boxes": [{"page": 1, "x": 0.5, "y": 0.1, "w": 0.2, "h": 0.03}]},
    ]
    bound = tt.bind(record, {"title": "Check 2 key fields", "document": "fil_1", "fields": fields})
    doc = next(r for r in bound["regions"] if r["region"] == "document")["data"]
    assert doc["file"] == "fil_1"
    assert doc["boxes"] == [
        {"key": "amount", "page": 1, "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.04, "check": True},
        {"key": "case_no", "page": 1, "x": 0.5, "y": 0.1, "w": 0.2, "h": 0.03, "check": False},
    ]


async def test_a_newer_seed_version_reaches_a_tenant_that_has_the_old_one() -> None:
    """A seed changed in the file under a new version is published to tenants already holding the old one, whose
    version stays readable for the tasks pinned to it."""
    db = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with db.begin() as conn:
        await conn.run_sync(metadata.create_all)
    seed = next(s for s in tt.seeds() if s["id"] == "generic_decision")
    with tenant_scope("t1"):
        store = TaskTypeStore(db)
        await store.ensure_seeds([{**seed, "version": 1}])
        await store.ensure_seeds([{**seed, "version": 2, "name": "Decision v2"}])
        assert (await store.published("generic_decision"))[0] == 2
        assert (await store.published("generic_decision", 1))[1]["name"] == seed["name"]


def _typed_flow(wid: str, task_type: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    review = {"title": "Check it", "taskType": task_type, "params": params}
    return {
        "schemaVersion": 2,
        "id": wid,
        "nodes": [
            {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {"id": "check", "type": "ops.flow.humanReview", "typeVersion": 1, "parameters": review},
            {"id": "ok", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "ok"}},
            {"id": "no", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "no"}},
        ],
        "connections": [
            {"from": {"node": "in", "port": "payload"}, "to": {"node": "check", "port": "in"}},
            {"from": {"node": "check", "port": "approve"}, "to": {"node": "ok", "port": "in"}},
            {"from": {"node": "check", "port": "reject"}, "to": {"node": "no", "port": "in"}},
        ],
    }


async def test_a_typed_step_missing_a_param_saves_with_a_warning_never_a_refusal(c: AsyncClient) -> None:
    """Owner, 2026-10-18: a missing setting warns on save and the task shows its fallback; it never refuses."""
    flow = _typed_flow("typed_warn", {"id": "generic_decision"}, {"facts": "$.input.facts"})
    saved = ok(await c.post("/v1/workflows/definitions", json={"definition": flow}, headers=BUILDER), 201)
    assert [(w["node"], w["field"]) for w in saved["warnings"]] == [("check", "params.title")], saved
    unknown = _typed_flow("typed_unknown", {"id": "no_such_type"}, {"title": "$.input.title"})
    saved = ok(await c.post("/v1/workflows/definitions", json={"definition": unknown}, headers=BUILDER), 201)
    assert [(w["node"], w["field"]) for w in saved["warnings"]] == [("check", "taskType")], saved


def test_dates_and_numbers_read_as_a_person_reads_them() -> None:
    """A raw ISO date or float never reaches a task's text or facts (uc-234 step 8, opsai-worker-ui)."""
    record = next(s for s in tt.seeds() if s["id"] == "tool_access_request")
    until = "2027-01-17T13:17:27.879526+00:00"
    facts = [{"label": "Until", "value": until}, {"label": "Calls a day", "value": 1200.0}]
    bound = tt.bind(record, {"title": "Dispute email asks to use Core banking", "until": until, "facts": facts}, worded)
    assert bound["actions"][0]["consequence"] == "The tools can be used until 17 Jan 2027."
    shown_facts = next(r for r in bound["regions"] if r["region"] == "facts")["data"]["facts"]
    assert [f["value"] for f in shown_facts] == ["17 Jan 2027", "1,200"]


def test_the_document_region_reads_boxes_from_an_extract_steps_fields() -> None:
    """An Extract from file step's `fields` is a dict by key, each with its boxes and needsReview."""
    record = next(s for s in tt.seeds() if s["id"] == "document_check")
    read: dict[str, Any] = {
        "amount": {
            "value": 3250.0,
            "needsReview": True,
            "boxes": [{"page": 1, "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.04}],
        },
        "court": {"value": "Nova Scotia Supreme Court", "needsReview": False, "boxes": []},
    }
    bound = tt.bind(record, {"title": "Check the read", "document": "fil_1", "fields": read})
    doc = next(r for r in bound["regions"] if r["region"] == "document")["data"]
    assert doc["boxes"] == [{"key": "amount", "page": 1, "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.04, "check": True}]
