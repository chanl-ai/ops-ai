"""Installing a plugin's skill and workflow as a team's own copies (c-590), through the real routes, by failure mode:
a copy skips the checks its create route makes, so a skill names a tool the team cannot call or a workflow that fails
the engine's checks is saved; a copy lands live instead of as a draft; a workflow copy takes the template's id, so a
second team's install collides with the first; and a copy is visible to, or changed by, another team.

tools-service is faked at its client, as in test_template_install."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic_ai.models.test import TestModel

from ..engine.test_lifecycle_rights import person
from .role_app import ok, role_app
from .test_template_install import SOURCE, TOOLS, wire

OPS = person("james", "team_ops", "builder")
LENDING = person("lena", "team_lending", "builder")

SKILL = {
    "source": SOURCE,
    "plugin": {"id": "test.templates", "title": "Case desk", "version": "0.2.0"},
    "kind": "skill",
    "id": "close-politely",
    "version": 1,
    "title": "Close a case politely",
    "requires": {"tools": TOOLS[1:], "bind": []},
    "digest": "c" * 64,
    "body": {
        "name": "Close a case politely",
        "use_when": "The person asks to close a case",
        "instructions": "Before closing a case, say what will happen to it and ask the person to confirm.",
    },
}
WORKFLOW = {
    "source": SOURCE,
    "plugin": SKILL["plugin"],
    "kind": "workflow",
    "id": "case-review",
    "version": 1,
    "title": "Case review",
    "requires": {"tools": TOOLS[:1], "bind": []},
    "digest": "d" * 64,
    "body": {
        "schemaVersion": 2,
        "id": "case_review",
        "name": "Case review",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "name": "Request"},
            {
                "id": "read",
                "type": "ops.action.tool",
                "typeVersion": 1,
                "name": "Read the case",
                "parameters": {"operation": "templates_get_case", "input": {"id": "$.input.caseId"}},
            },
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Read", "parameters": {"outcome": "read"}},
            {
                "id": "failed",
                "type": "ops.flow.end",
                "typeVersion": 1,
                "name": "Not read",
                "parameters": {"outcome": "not_read", "result": "failed"},
            },
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "read", "port": "in"}},
            {"from": {"node": "read", "port": "ok"}, "to": {"node": "done", "port": "in"}},
            {"from": {"node": "read", "port": "refused"}, "to": {"node": "failed", "port": "in"}},
            {"from": {"node": "read", "port": "error"}, "to": {"node": "failed", "port": "in"}},
        ],
    },
}


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    async with role_app(TestModel()) as c:
        yield c


async def install(client: AsyncClient, tid: str, who: dict[str, str] = OPS, **body: Any) -> Any:
    return await client.post(f"/v1/templates/{SOURCE}/{tid}/install", json=body, headers=who)


async def test_a_skill_copy_is_the_teams_draft_and_its_tools_are_checked(client: AsyncClient) -> None:
    wire(client, [SKILL], tools=TOOLS[:1])  # the team is not offered close_case
    refused = await install(client, "close-politely")
    assert refused.status_code in (400, 422), refused.text
    assert ok(await client.get("/v1/templates", params={"kind": "skill"}, headers=OPS))[0]["installed"]["copies"] == 0
    wire(client, [SKILL])
    made = ok(await install(client, "close-politely"), 201)["copy"]
    skill = ok(await client.get(f"/v1/skills/{made['recordId']}", headers=OPS))
    assert skill["name"] == "Close a case politely" and skill["status"] != "published"
    assert [t["toolId"] for t in skill["content"]["tools"]] == TOOLS[1:]


async def test_a_workflow_copy_is_a_draft_of_its_own_id_in_each_team(client: AsyncClient) -> None:
    wire(client, [WORKFLOW])
    mine = ok(await install(client, "case-review"), 201)["copy"]
    theirs = ok(await install(client, "case-review", LENDING), 201)["copy"]
    assert mine["recordId"] != theirs["recordId"] and mine["recordId"].startswith("case_review")
    held = ok(await client.get(f"/v1/workflows/definitions/{mine['recordId']}", headers=OPS))
    assert held["stage"] != "live"
    hidden = await client.get(f"/v1/workflows/definitions/{mine['recordId']}", headers=LENDING)
    assert hidden.status_code in (403, 404), hidden.text


async def test_a_workflow_that_fails_the_engines_checks_is_refused_and_nothing_is_made(client: AsyncClient) -> None:
    broken = WORKFLOW | {"body": {**WORKFLOW["body"], "connections": []}}  # type: ignore[dict-item]
    wire(client, [broken])
    r = await install(client, "case-review")
    assert r.status_code == 422 and r.json()["error"]["code"] == "definition_checks", r.text
    listed = ok(await client.get("/v1/templates", params={"kind": "workflow"}, headers=OPS))
    assert listed[0]["installed"]["copies"] == 0


async def test_deleting_a_skill_or_workflow_copy_marks_it_removed(client: AsyncClient) -> None:
    wire(client, [SKILL, WORKFLOW])
    sid = ok(await install(client, "close-politely"), 201)["copy"]["recordId"]
    wid = ok(await install(client, "case-review"), 201)["copy"]["recordId"]
    for path in (f"/v1/skills/{sid}", f"/v1/workflows/definitions/{wid}"):
        gone = await client.delete(path, headers=OPS)
        assert gone.status_code == 204, gone.text
    listed = ok(await client.get("/v1/templates", headers=OPS))
    assert {t["id"]: t["installed"]["copies"] for t in listed} == {"close-politely": 0, "case-review": 0}
