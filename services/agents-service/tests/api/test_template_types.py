"""Case and task types from a template, through the real routes, by failure mode: two packs that ship a type with the
same id cross over (an update from one writes into the other's copy, or the second copy takes the first's id); a copy
is made some way other than the type's own create route; and an update replaces a field definition the team edited,
or skips one the team never touched.

tools-service is faked at its client, as in test_template_install."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic_ai.models.test import TestModel

from .role_app import ok, role_app
from .test_template_install import wire
from .test_template_update import OPS


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    async with role_app(TestModel()) as c:
        yield c


SEEDS = Path(__file__).parents[2] / "seed"

A, B = "plugin:test.core", "plugin:test.other"
DECISION = next(t for t in json.loads((SEEDS / "task_types.json").read_text()) if t["id"] == "generic_decision")


def dispute(source: str, version: int = 1, **label: str) -> dict[str, Any]:
    """Case type `dispute` as a pack ships it; `label` relabels a field by key."""
    fields = [
        {"key": "amount", "label": "Amount", "type": "money"},
        {"key": "opened", "label": "Opened", "type": "date"},
    ]
    return {
        "source": source,
        "plugin": {"id": source.removeprefix("plugin:"), "title": source.removeprefix("plugin:test."), "version": "1"},
        "kind": "case_type",
        "id": "dispute",
        "version": version,
        "title": "Dispute",
        "requires": {"tools": [], "bind": []},
        "digest": f"{source[-1]}{version}" * 32,
        "body": {
            "id": "dispute",
            "name": "Dispute",
            "description": "A customer disputes a charge",
            "fields": [f | {"label": label.get(f["key"], f["label"])} for f in fields],
        },
    }


def callback(version: int = 1) -> dict[str, Any]:
    return {
        "source": A,
        "plugin": {"id": "test.core", "title": "core", "version": "1"},
        "kind": "task_type",
        "id": "callback",
        "version": version,
        "title": "Call back",
        "requires": {"tools": [], "bind": []},
        "digest": f"t{version}" * 32,
        # The seeded general decision type's definition, so the body is one the task type create accepts.
        "body": {**{k: DECISION[k] for k in ("params", "regions", "actions")}, "id": "callback", "name": "Call back"},
    }


async def add(client: AsyncClient, source: str, tid: str = "dispute", **body: Any) -> dict[str, Any]:
    return dict(ok(await client.post(f"/v1/resources/{source}:{tid}/copies", json=body, headers=OPS), 201)["copy"])


def state(rows: list[dict[str, Any]], source: str, tid: str = "dispute") -> str:
    return next(str(r["state"]) for r in rows if r["source"] == source and r["id"] == tid)


async def test_two_packs_shipping_the_same_case_type_make_two_types_and_never_cross_over(client: AsyncClient) -> None:
    wire(client, [dispute(A), dispute(B), callback()])
    mine = await add(client, A)
    # The copy is the team's own type, with its own id; the template id lives on the copy link only.
    assert mine["recordId"] != "dispute" and mine["kind"] == "case_type"
    made = ok(await client.get(f"/v1/case-types/{mine['recordId']}", headers=OPS))
    assert made["name"] == "Dispute" and made["versions"][0]["record"]["fields"][0]["key"] == "amount"
    task = await add(client, A, "callback")
    assert ok(await client.get(f"/v1/task-types/{task['recordId']}", headers=OPS))["name"] == "Call back"
    # B changes its dispute: A's copy is offered nothing.
    wire(client, [dispute(A), dispute(B, 2, amount="Disputed amount"), callback()])
    rows = ok(await client.get("/v1/templates", headers=OPS))
    assert (state(rows, A), state(rows, B)) == ("added", "available"), rows
    # Adding B's under the name A's holds asks for another; under another name it is a second type beside A's.
    taken = await client.post(f"/v1/resources/{B}:dispute/copies", json={}, headers=OPS)
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "name_taken", taken.text
    theirs = await add(client, B, name="Dispute, other")
    assert theirs["recordId"] not in (mine["recordId"], "dispute")
    assert (
        ok(await client.get(f"/v1/case-types/{mine['recordId']}", headers=OPS))["versions"][0]["record"]["fields"][0][
            "label"
        ]
        == "Amount"
    )


async def test_a_case_type_update_keeps_the_teams_field_and_takes_the_templates(client: AsyncClient) -> None:
    wire(client, [dispute(A)])
    type_id = (await add(client, A))["recordId"]
    own = {
        "name": "Dispute",
        "description": "A customer disputes a charge",
        "fields": [
            {"key": "amount", "label": "Amount", "type": "money"},
            {"key": "opened", "label": "Date opened", "type": "date"},
        ],
    }
    saved = await client.put(f"/v1/case-types/{type_id}/draft", json=own, headers=OPS)
    assert saved.status_code == 200, saved.text
    wire(client, [dispute(A, 2, amount="Disputed amount")])
    path = f"/v1/resources/{A}:dispute/copies/{type_id}/update"
    review = ok(await client.get(path, headers=OPS))
    assert {f["field"]: f["outcome"] for f in review["fields"]} == {
        "field:amount": "taken",
        "field:opened": "kept",
    }, review["fields"]
    ok(await client.post(path, json={"expect": review["expect"]}, headers=OPS))
    newest = ok(await client.get(f"/v1/case-types/{type_id}", headers=OPS))["versions"][0]["record"]
    assert [f["label"] for f in newest["fields"]] == ["Disputed amount", "Date opened"]
