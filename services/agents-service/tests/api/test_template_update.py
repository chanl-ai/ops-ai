"""Taking a template update into a team's copy, field by field, through the real routes, by failure mode: an update
overwrites a field the team edited (and, after a conflict kept as the team's, the next update overwrites it); an update
skips a field the team never touched; an update rewrites a published version, or a workflow version lands live; the
base is lost when the team saves over its draft; an open draft's edits are wiped, or a draft under review is
rewritten; a detached copy is still updated; a member takes an update or a session in no team detaches; a stale
review is applied; an update saves a tool the team cannot call; an edited workflow is replaced, or a kept workflow
conflict is offered forever; and Add after a pin moves makes a second live copy.

tools-service is faked at its client, as in test_template_install: moving a pin is answering a new template body."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic_ai.models.test import TestModel
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import Pool, StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_agents.store.skills import SkillVersionRow
from ops_engine.store import metadata as engine_metadata
from ops_service_kit.settings import Settings

from ..conftest import SEED, FakeGraphModels
from ..engine.test_lifecycle_rights import person
from ..saves import save_skill_draft
from .role_app import ok, role_app
from .test_reply_pins import FIXTURES, answer, compare
from .test_template_install import AGENT, SOURCE, TOOLS, wire
from .test_template_install_kinds import WORKFLOW
from .test_workflow_routes import _held_by_request  # pyright: ignore[reportPrivateUsage]

OPS = person("james", "team_ops", "builder")
VIEWER = person("vera", "team_ops", "viewer")
SKILL: dict[str, Any] = {
    "source": SOURCE,
    "plugin": {"id": "test.templates", "title": "Case desk", "version": "0.2.0"},
    "kind": "skill",
    "id": "cite-policy",
    "version": 1,
    "title": "Cite the policy",
    "requires": {"tools": TOOLS[:1], "bind": []},
    "digest": "1" * 64,
    "body": {
        "name": "Cite the policy",
        "use_when": "A customer asks why a fee was charged",
        "instructions": "Quote the fee schedule section that applies.",
    },
}


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    async with role_app(TestModel()) as c:
        yield c


def pack(version: int, **body: str) -> dict[str, Any]:
    """The skill template as a later pin ships it."""
    return SKILL | {"version": version, "digest": str(version) * 64, "body": {**SKILL["body"], **body}}


def store(client: AsyncClient) -> Any:
    return client._transport.app.state.runtime  # type: ignore[attr-defined]


async def add_skill(client: AsyncClient) -> str:
    wire(client, [SKILL])
    made = ok(await client.post(f"/v1/resources/{SOURCE}:cite-policy/copies", json={}, headers=OPS), 201)
    return str(made["copy"]["recordId"])


async def edit_skill(client: AsyncClient, sid: str, **fields: Any) -> None:
    held = ok(await client.get(f"/v1/skills/{sid}", headers=OPS))
    body = {"baseVersion": held["version"], "note": "", **fields}
    ok(await save_skill_draft(client, sid, body, headers=OPS))


async def publish_skill(client: AsyncClient, sid: str) -> int:
    from ops_agents.api.skills import skills  # noqa: PLC0415 - the review is not this test's subject

    reg = skills(store(client))
    n = (await reg.row(sid)).version
    await reg.publish(sid, n, by="approver@harborpine.example", review_id="rv_test")
    return n


async def versions(client: AsyncClient, sid: str) -> list[SkillVersionRow]:
    from ops_agents.api.skills import skills  # noqa: PLC0415

    return await skills(store(client)).versions(sid)


def path(sid: str, tid: str = "cite-policy") -> str:
    return f"/v1/resources/{SOURCE}:{tid}/copies/{sid}/update"


def outcomes(review: dict[str, Any]) -> dict[str, str]:
    return {f["field"]: f["outcome"] for f in review["fields"]}


async def test_a_skill_the_team_edited_keeps_its_edit_takes_the_rest_and_asks_again_next_time(
    client: AsyncClient,
) -> None:
    """The brief's case: a team edited a skill's instructions, then the template changed its instructions and its use
    when. The update keeps the team's instructions, takes the use when, lands as a draft beside the published version,
    and a later template change to the instructions is a choice again, never taken."""
    sid = await add_skill(client)
    await edit_skill(client, sid, instructions="Quote the fee schedule and the date it took effect.")
    published = await publish_skill(client, sid)
    before = {v.version: v.digest for v in await versions(client, sid)}
    wire(client, [pack(2, instructions="Quote the section and link it.", use_when="A customer disputes a fee")])
    listed = ok(await client.get("/v1/templates", params={"kind": "skill"}, headers=OPS))
    assert listed[0]["state"] == "update_available"
    review = ok(await client.get(path(sid), headers=OPS))
    assert outcomes(review) == {"useWhen": "taken", "instructions": "conflict"} and review["draftOpen"] is False
    taken = ok(await client.post(path(sid), json={"expect": review["expect"]}, headers=OPS))
    assert taken["version"] == published + 1
    newest = (await versions(client, sid))[0]
    assert newest.published_at is None
    assert newest.content["instructions"] == "Quote the fee schedule and the date it took effect."
    assert newest.content["useWhen"] == "A customer disputes a fee"
    after = {v.version: v.digest for v in await versions(client, sid)}
    assert after[published] == before[published]
    wire(client, [pack(3, instructions="Quote the section, link it, and name the owner.")])
    again = ok(await client.get(path(sid), headers=OPS))
    assert outcomes(again)["instructions"] == "conflict"


async def test_a_conflict_the_person_settles_for_the_template_is_written(client: AsyncClient) -> None:
    sid = await add_skill(client)
    await edit_skill(client, sid, instructions="Quote the schedule.")
    wire(client, [pack(2, instructions="Quote the section and link it.")])
    taken = ok(await client.post(path(sid), json={"choices": {"instructions": "template"}}, headers=OPS))
    assert taken["taken"] is True
    assert (await versions(client, sid))[0].content["instructions"] == "Quote the section and link it."


async def test_the_base_survives_the_team_saving_over_its_draft_twice(client: AsyncClient) -> None:
    sid = await add_skill(client)
    await edit_skill(client, sid, instructions="Quote the schedule.")
    await edit_skill(client, sid, guardrails=["Never quote a fee that is not in the schedule"])
    wire(client, [pack(2, use_when="A customer disputes a fee")])
    review = ok(await client.get(path(sid), headers=OPS))
    assert outcomes(review) == {"useWhen": "taken", "instructions": "kept", "guardrails": "kept"}
    ok(await client.post(path(sid), json={}, headers=OPS))
    content = (await versions(client, sid))[0].content
    assert content["instructions"] == "Quote the schedule." and content["useWhen"] == "A customer disputes a fee"
    assert content["guardrails"] == ["Never quote a fee that is not in the schedule"]


async def test_an_open_skill_draft_is_merged_into_and_keeps_its_edit(client: AsyncClient) -> None:
    sid = await add_skill(client)
    published = await publish_skill(client, sid)
    await edit_skill(client, sid, instructions="Quote the schedule.")
    wire(client, [pack(2, instructions="Quote the section and link it.", use_when="A customer disputes a fee")])
    review = ok(await client.get(path(sid), headers=OPS))
    assert review["draftOpen"] is True
    taken = ok(await client.post(path(sid), json={}, headers=OPS))
    assert taken["version"] == published + 1 and len(await versions(client, sid)) == published + 1
    assert (await versions(client, sid))[0].content["instructions"] == "Quote the schedule."


async def test_an_agent_draft_under_review_is_never_rewritten(client: AsyncClient) -> None:
    wire(client, [AGENT])
    aid = ok(await client.post(f"/v1/resources/{SOURCE}:case-helper/copies", json={}, headers=OPS), 201)
    aid = aid["copy"]["recordId"]
    rt = store(client)
    rt.settings = rt.settings.model_copy(update={"registry_auto_approve": False})
    asked = ok(await client.post(f"/v1/agents/{aid}/publish-requests", json={"version": 1}, headers=OPS), 201)
    assert asked["status"] == "pending", asked
    body = cast(dict[str, Any], AGENT["body"])
    wire(client, [AGENT | {"version": 3, "digest": "b" * 64, "body": {**body, "role": "Reads cases"}}])
    taken = ok(await client.post(f"/v1/resources/{SOURCE}:case-helper/copies/{aid}/update", json={}, headers=OPS))
    assert taken["version"] == 2
    from ops_agents.api.agent_registry import registry  # noqa: PLC0415

    held = await registry(store(client)).versions(aid)
    by_version = {v.version: v.spec["role"] for v in held}
    assert by_version == {2: "Reads cases", 1: str(body["role"])}


async def test_a_stale_review_is_refused_and_saves_nothing(client: AsyncClient) -> None:
    sid = await add_skill(client)
    wire(client, [pack(2, use_when="A customer disputes a fee")])
    review = ok(await client.get(path(sid), headers=OPS))
    wire(client, [pack(3, use_when="A customer disputes a charge")])
    stale = await client.post(path(sid), json={"expect": review["expect"]}, headers=OPS)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "update_stale", stale.text
    assert len(await versions(client, sid)) == 1
    assert (await versions(client, sid))[0].content["useWhen"] == SKILL["body"]["use_when"]


async def test_a_detached_copy_takes_no_update_and_its_template_is_offered_again(client: AsyncClient) -> None:
    sid = await add_skill(client)
    detach = f"/v1/resources/{SOURCE}:cite-policy/copies/{sid}/detach"
    first = ok(await client.post(detach, headers=OPS))
    again = ok(await client.post(detach, headers=OPS))
    assert first["detachedAt"] and again["detachedAt"] == first["detachedAt"]
    wire(client, [pack(2, use_when="A customer disputes a fee")])
    refused = await client.get(path(sid), headers=OPS)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "detached", refused.text
    listed = ok(await client.get("/v1/templates", params={"kind": "skill"}, headers=OPS))
    assert listed[0]["state"] == "available"


async def test_a_member_cannot_update_reset_or_detach(client: AsyncClient) -> None:
    sid = await add_skill(client)
    wire(client, [pack(2, use_when="A customer disputes a fee")])
    for r in (
        await client.post(path(sid), json={}, headers=VIEWER),
        await client.post(path(sid), json={"mode": "reset", "confirm": True}, headers=VIEWER),
        await client.post(f"/v1/resources/{SOURCE}:cite-policy/copies/{sid}/detach", headers=VIEWER),
    ):
        assert r.status_code == 403, r.text
    assert len(await versions(client, sid)) == 1


async def test_a_session_acting_in_no_team_cannot_detach() -> None:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    app = create_app(
        Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED),
        model=TestModel(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
    )
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(app.router.lifespan_context(app))
        client = await stack.enter_async_context(AsyncClient(transport=ASGITransport(app=app), base_url="http://t"))
        wire(client, [SKILL])
        detach = f"/v1/resources/{SOURCE}:cite-policy/copies/sk_x/detach"
        r = await client.post(detach, headers={"X-Team-Id": "team_ops"})
        assert r.status_code == 400 and r.json()["error"]["code"] == "team_required", r.text


async def test_an_update_naming_a_tool_the_team_cannot_call_is_refused_and_saves_nothing(
    client: AsyncClient,
) -> None:
    wire(client, [AGENT])
    aid = ok(await client.post(f"/v1/resources/{SOURCE}:case-helper/copies", json={}, headers=OPS), 201)
    aid = aid["copy"]["recordId"]
    more: dict[str, Any] = AGENT | {
        "version": 3,
        "requires": {**cast(dict[str, Any], AGENT["requires"]), "tools": [*TOOLS, "billing_refund"]},
    }
    wire(client, [more])
    r = await client.post(f"/v1/resources/{SOURCE}:case-helper/copies/{aid}/update", json={}, headers=OPS)
    # 422, not the add path's 400: the request is well formed, and the template asks for what the team lacks.
    assert r.status_code == 422 and r.json()["error"]["code"] == "tool_not_available", r.text
    assert r.json()["error"]["details"]["tools"] == ["billing_refund"]
    assert "billing_refund" in r.json()["error"]["message"]
    from ops_agents.api.agent_registry import registry  # noqa: PLC0415

    assert len(await registry(store(client)).versions(aid)) == 1


async def test_add_after_the_pin_moves_answers_the_copy_the_team_holds(client: AsyncClient) -> None:
    sid = await add_skill(client)
    wire(client, [pack(2, use_when="A customer disputes a fee")])
    again = ok(await client.post(f"/v1/resources/{SOURCE}:cite-policy/copies", json={}, headers=OPS), 200)
    assert again["created"] is False and again["copy"]["recordId"] == sid and again["copy"]["version"] == 1


async def test_an_edited_workflow_keeps_its_definition_and_is_not_offered_the_same_update_again(
    client: AsyncClient,
) -> None:
    wire(client, [WORKFLOW])
    made = ok(await client.post(f"/v1/resources/{SOURCE}:case-review/copies", json={}, headers=OPS), 201)["copy"]
    wid = made["recordId"]
    held = ok(await client.get(f"/v1/workflows/definitions/{wid}", headers=OPS))
    edited = {**held["definition"], "description": "Reads the case before the review meeting"}
    saved = await client.post("/v1/workflows/definitions", json={"definition": edited}, headers=OPS)
    assert saved.status_code in (200, 201), saved.text
    wire(client, [WORKFLOW | {"version": 2, "digest": "e" * 64}])
    upd = f"/v1/resources/{SOURCE}:case-review/copies/{wid}/update"
    review = ok(await client.get(upd, headers=OPS))
    assert outcomes(review) == {"definition": "conflict"}
    taken = ok(await client.post(upd, json={}, headers=OPS))
    assert taken["version"] is None and taken["copy"]["version"] == 2
    kept = ok(await client.get(f"/v1/workflows/definitions/{wid}", headers=OPS))
    assert kept["definition"].get("description") == "Reads the case before the review meeting"
    listed = ok(await client.get("/v1/templates", params={"kind": "workflow"}, headers=OPS))
    assert listed[0]["state"] == "added"


async def test_a_second_team_adds_the_same_skill_template_as_its_own(client: AsyncClient) -> None:
    lending = person("lena", "team_lending", "builder")
    first = await add_skill(client)
    made = await client.post(f"/v1/resources/{SOURCE}:cite-policy/copies", json={}, headers=lending)
    assert made.status_code == 201, made.text
    second = made.json()["data"]["copy"]["recordId"]
    assert second != first
    theirs = ok(await client.get(f"/v1/skills/{second}", headers=lending))
    assert theirs["name"] == "Cite the policy" and theirs["slug"] == "cite-the-policy"
    clash = await client.post(
        "/v1/skills",
        json={"name": "Cite the policy", "useWhen": "Asked", "instructions": "Another.", "ownerTeam": "team_ops"},
        headers=OPS,
    )
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "name_taken", clash.text


# (name, method, path, body): `{sid}` is the skill copy the first copy row makes; a "wire" row ships the next version.
PINNED: list[tuple[str, str, str, Any]] = [
    ("list", "get", "/v1/templates?kind=skill", None),
    ("copy", "post", f"/v1/resources/{SOURCE}:cite-policy/copies", {}),
    ("copy.again", "post", f"/v1/resources/{SOURCE}:cite-policy/copies", {}),
    ("copy.unknownField", "post", f"/v1/resources/{SOURCE}:cite-policy/copies", {"colour": "red"}),
    ("copy.missing", "post", f"/v1/resources/{SOURCE}:nowhere/copies", {}),
    ("plan", "post", "/v1/resources/plan", {"resources": [f"{SOURCE}:cite-policy"]}),
    ("plan.empty", "post", "/v1/resources/plan", {"resources": []}),
    ("next", "wire", "", None),
    ("review", "get", "/v1/resources/{res}/copies/{sid}/update", None),
    ("take.unknownField", "post", "/v1/resources/{res}/copies/{sid}/update", {"how": "now"}),
    ("take", "post", "/v1/resources/{res}/copies/{sid}/update", {}),
    ("detach.notTheCopy", "post", "/v1/resources/{res}/copies/sk_missing1/detach", None),
    ("detach", "post", "/v1/resources/{res}/copies/{sid}/detach", None),
    ("detach.again", "post", "/v1/resources/{res}/copies/{sid}/detach", None),
]


async def _send(client: AsyncClient, method: str, path: str, body: Any, sid: str) -> Any:
    url = path.replace("{res}", f"{SOURCE}:cite-policy").replace("{sid}", sid)
    return await client.request(method, url, headers=OPS, **({} if body is None else {"json": body}))


async def test_the_template_routes_keep_every_key_value_and_error_object(client: AsyncClient) -> None:
    wire(client, [SKILL])
    seen: dict[str, Any] = {}
    sid = ""
    for name, method, path, body in PINNED:
        if method == "wire":
            wire(client, [pack(2, use_when="A customer disputes a fee")])
            continue
        r = await _send(client, method, path, body, sid)
        sid = sid or (r.json()["data"]["copy"]["recordId"] if name == "copy" else "")
        seen[name] = answer(r)
    compare(json.loads(json.dumps(seen).replace(sid, "<sk>")), FIXTURES / "reply-pins-templates.json")


async def test_no_connection_is_held_while_tools_service_answers_and_a_detach_takes_one(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every route but the detach asks tools-service for the team's templates: none holds a connection while it
    answers. The detach reads and writes only this service's rows, in one request transaction."""
    templates = wire(client, [SKILL])
    sid = await add_skill(client)
    wire(client, [pack(2, use_when="A customer disputes a fee")])
    with _held_by_request() as held:
        asked: list[int] = []
        real = type(templates).get

        async def watched(self: Any, *args: Any, **kwargs: Any) -> Any:
            asked.append(held())
            return await real(self, *args, **kwargs)

        monkeypatch.setattr(type(templates), "get", watched)
        res = f"/v1/resources/{SOURCE}:cite-policy"
        codes = [
            (await client.get("/v1/templates", headers=OPS)).status_code,
            (await client.post(f"{res}/copies", json={}, headers=OPS)).status_code,
            (
                await client.post("/v1/resources/plan", json={"resources": [f"{SOURCE}:cite-policy"]}, headers=OPS)
            ).status_code,
            (await client.get(path(sid), headers=OPS)).status_code,
            (await client.post(path(sid), json={}, headers=OPS)).status_code,
        ]
        task, checkouts = asyncio.current_task(), [0]

        def checked_out(*_: object) -> None:
            checkouts[0] += asyncio.current_task() is task

        event.listen(Pool, "checkout", checked_out)
        try:
            detached = await client.post(f"{res}/copies/{sid}/detach", headers=OPS)
        finally:
            event.remove(Pool, "checkout", checked_out)
    assert (codes, set(asked), detached.status_code, checkouts) == ([200] * 5, {0}, 200, [1])
