"""/v1/guardrails and agent pins (c-063 T001, T002). Failure modes: a guardrail with no topic or no message saved; a
draft guardrail pinned; an edit to a guardrail changing what a pinned agent enforces; a deprecated guardrail taking a
new pin or a pinned one losing its existing pin; a pinned guardrail deleted; the publish decided by its requester; a
published pin not reaching the definition the runtime serves; a topic's scope lost between the save and the served
definition; the paged list answering every row, or a total that ignores the search; a page that loads the whole
table."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from httpx import AsyncClient
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ops_agents.store.guardrails import GuardrailRegistry

from .test_agent_registry import _app, _ok  # pyright: ignore[reportPrivateUsage]

LEE = {"X-Dev-User": "lee@northfieldbank.com"}
KIM = {"X-Dev-User": "kim@northfieldbank.com"}
ADVISOR = "ag_branch"
RULE = {"name": "No investment advice", "topics": ["investment advice"], "message": "I can't give investment advice."}


async def _published(c: AsyncClient) -> dict[str, Any]:
    g = _ok(await c.post("/v1/guardrails", json=RULE), 201)
    return _ok(await c.post(f"/v1/guardrails/{g['id']}/publish-requests", json={"version": 1}), 201)


async def _pin(c: AsyncClient, gid: str, version: int) -> Any:
    return await c.patch(f"/v1/agents/{ADVISOR}", json={"guardrailPins": [{"guardrailId": gid, "version": version}]})


async def test_a_guardrail_needs_a_topic_and_a_message(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        r = await c.post("/v1/guardrails", json={**RULE, "topics": [" "]})
        assert (r.status_code, r.json()["error"]["code"]) == (400, "no_topics")
        r = await c.post("/v1/guardrails", json={**RULE, "message": ""})
        assert r.json()["error"]["code"] == "no_message"


async def test_only_a_published_version_pins_and_the_pin_keeps_its_version(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        draft = _ok(await c.post("/v1/guardrails", json=RULE), 201)
        r = await _pin(c, draft["id"], 1)
        assert (r.status_code, r.json()["error"]["code"]) == (422, "not_published")

        g = await _published(c)
        agent = _ok(await _pin(c, g["id"], 1))
        assert agent["guardrailPins"] == [
            {
                "guardrailId": g["id"],
                "version": 1,
                "name": RULE["name"],
                "topics": ["investment advice"],
                "enabled": True,
            }
        ]
        # A later version of the guardrail does not change what the agent pins.
        _ok(await c.patch(f"/v1/guardrails/{g['id']}", json={"topics": ["investment advice", "tax advice"]}))
        _ok(await c.post(f"/v1/guardrails/{g['id']}/publish-requests", json={"version": 2}), 201)
        agent = _ok(await c.get(f"/v1/agents/{ADVISOR}"))
        assert agent["guardrailPins"][0]["topics"] == ["investment advice"]
        assert _ok(await c.get(f"/v1/guardrails/{g['id']}"))["usedBy"] == [agent["name"]]


async def test_a_published_pin_reaches_the_served_definition(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        g = await _published(c)
        agent = _ok(await _pin(c, g["id"], 1))
        _ok(await c.post(f"/v1/agents/{ADVISOR}/publish-requests", json={"version": agent["version"]}), 201)
        app = cast(Any, c)._transport.app
        served = app.state.runtime.catalog.agent(ADVISOR)
        assert [(r.guardrail_id, r.version, r.message) for r in served.guardrails] == [(g["id"], 1, RULE["message"])]


async def test_a_topic_scope_is_versioned_and_reaches_the_served_definition(tmp_path: Path) -> None:
    scope = "Whether to buy, sell or hold a security. Not: the bank's own deposit products."
    async with _app(str(tmp_path / "db.sqlite")) as c:
        g = _ok(await c.post("/v1/guardrails", json={**RULE, "scopes": {"investment advice": scope}}), 201)
        assert g["config"]["scopes"] == {"investment advice": scope}
        _ok(await c.post(f"/v1/guardrails/{g['id']}/publish-requests", json={"version": 1}), 201)
        agent = _ok(await _pin(c, g["id"], 1))
        _ok(await c.post(f"/v1/agents/{ADVISOR}/publish-requests", json={"version": agent["version"]}), 201)
        served = cast(Any, c)._transport.app.state.runtime.catalog.agent(ADVISOR)
        assert [r.scopes for r in served.guardrails] == [{"investment advice": scope}]
        # v2 blocks another topic: the scope of the dropped topic goes with it, and v1 keeps its own.
        v2 = _ok(await c.patch(f"/v1/guardrails/{g['id']}", json={"topics": ["tax advice"]}))
        assert "scopes" not in v2["versions"][0]["config"]
        assert v2["versions"][1]["config"]["scopes"] == {"investment advice": scope}


async def test_deprecated_takes_no_new_pin_but_keeps_existing_ones(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        g = await _published(c)
        _ok(await _pin(c, g["id"], 1))
        _ok(await c.post(f"/v1/guardrails/{g['id']}/status", json={"status": "deprecated"}))
        # A save that keeps the pin goes through.
        _ok(
            await c.patch(
                f"/v1/agents/{ADVISOR}",
                json={"role": "Answers bankers", "guardrailPins": [{"guardrailId": g["id"], "version": 1}]},
            )
        )
        other = _ok(await c.post("/v1/guardrails", json={**RULE, "name": "Other"}), 201)
        _ok(await c.post(f"/v1/guardrails/{other['id']}/publish-requests", json={"version": 1}), 201)
        _ok(await c.post(f"/v1/guardrails/{other['id']}/status", json={"status": "deprecated"}))
        r = await _pin(c, other["id"], 1)
        assert (r.status_code, r.json()["error"]["code"]) == (422, "guardrail_deprecated")


async def test_a_pinned_guardrail_cannot_be_deleted(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        g = await _published(c)
        _ok(await _pin(c, g["id"], 1))
        r = await c.delete(f"/v1/guardrails/{g['id']}")
        assert (r.status_code, r.json()["error"]["code"]) == (409, "guardrail_pinned")
        agent = _ok(await c.patch(f"/v1/agents/{ADVISOR}", json={"guardrailPins": []}))
        _ok(await c.post(f"/v1/agents/{ADVISOR}/publish-requests", json={"version": agent["version"]}), 201)
        assert (await c.delete(f"/v1/guardrails/{g['id']}")).status_code == 204


async def test_with_the_policy_off_the_requester_cannot_decide_a_guardrail_publish(tmp_path: Path) -> None:
    async with _app(
        str(tmp_path / "db.sqlite"), registry_auto_approve=False, dev_policies={"requesterMayDecide": False}
    ) as c:
        g = _ok(await c.post("/v1/guardrails", json=RULE, headers=LEE), 201)
        g = _ok(await c.post(f"/v1/guardrails/{g['id']}/publish-requests", json={"version": 1}, headers=LEE), 201)
        rid = g["pendingRequestId"]
        assert rid.startswith("GRP-")
        decide = f"/v1/guardrails/{g['id']}/publish-requests/{rid}/decision"
        r = await c.post(decide, json={"decision": "approved"}, headers=LEE)
        assert r.status_code == 403
        assert _ok(await c.get(f"/v1/guardrails/{g['id']}"))["publishedVersion"] is None
        _ok(await c.post(decide, json={"decision": "approved"}, headers=KIM))
        assert _ok(await c.get(f"/v1/guardrails/{g['id']}"))["publishedVersion"] == 1


async def test_a_guardrail_publish_decided_from_publish_requests_publishes_it(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite"), registry_auto_approve=False) as c:
        g = _ok(await c.post("/v1/guardrails", json=RULE, headers=LEE), 201)
        g = _ok(await c.post(f"/v1/guardrails/{g['id']}/publish-requests", json={"version": 1}, headers=LEE), 201)
        rid = g["pendingRequestId"]
        assert _ok(await c.get(f"/v1/publish-requests/{rid}"))["title"] == f"Publish {RULE['name']} v1"
        _ok(await c.post(f"/v1/publish-requests/{rid}/decision", json={"decision": "approved"}, headers=KIM))
        assert _ok(await c.get(f"/v1/guardrails/{g['id']}"))["publishedVersion"] == 1


async def test_only_the_creator_or_a_team_admin_deletes_a_guardrail(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        g = _ok(await c.post("/v1/guardrails", json=RULE, headers=LEE), 201)
        r = await c.delete(f"/v1/guardrails/{g['id']}", headers=KIM)
        assert r.status_code == 403, r.text
        assert (await c.delete(f"/v1/guardrails/{g['id']}", headers=LEE)).status_code == 204


async def test_the_paged_list_answers_one_page_and_the_searched_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        for i in range(5):
            _ok(await c.post("/v1/guardrails", json={**RULE, "name": f"Rule {i}", "topics": [f"topic {i}"]}), 201)
        whole = cast(list[dict[str, Any]], _ok(await c.get("/v1/guardrails")))
        assert isinstance(whole, list), "without page the pin picker still reads the whole list"

        # A page reads only its own rows: the whole-table read is never called, and the query answers at most a page.
        async def no_whole_table(_self: GuardrailRegistry) -> list[dict[str, Any]]:
            raise AssertionError("a page must not load every guardrail")

        monkeypatch.setattr(GuardrailRegistry, "rows", no_whole_table)
        p2 = _ok(await c.get("/v1/guardrails", params={"page": 2, "pageSize": 2}))
        assert [g["name"] for g in p2["data"]] == ["Rule 2", "Rule 3"]
        assert (p2["pagination"]["total"], p2["pagination"]["totalPages"]) == (len(whole), -(-len(whole) // 2))
        hit = _ok(await c.get("/v1/guardrails", params={"page": 1, "search": "rule 4"}))
        assert [g["name"] for g in hit["data"]] == ["Rule 4"] and hit["pagination"]["total"] == 1


async def test_wildcards_in_the_search_match_only_themselves(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        for n in ("Rate 100%", "Rate 1000", "a_b", "axb"):
            _ok(await c.post("/v1/guardrails", json={**RULE, "name": n}), 201)
        for term, want in (("100%", ["Rate 100%"]), ("a_b", ["a_b"])):
            got = _ok(await c.get("/v1/guardrails", params={"page": 1, "search": term}))
            assert [g["name"] for g in got["data"]] == want, term


async def test_hold_until_checked_is_versioned_and_reaches_the_served_definition(tmp_path: Path) -> None:
    # Chat streaming, 2026-10-18: a guarded answer streams and is replaced on a hit unless its rule holds it. A rule
    # saved without the setting keeps the shape it had, so its digest and every pin on it stay put.
    async with _app(str(tmp_path / "db.sqlite")) as c:
        held = _ok(await c.post("/v1/guardrails", json={**RULE, "holdUntilChecked": True}), 201)
        plain = _ok(await c.post("/v1/guardrails", json={**RULE, "name": "Streamed"}), 201)
        assert held["config"]["holdUntilChecked"] is True and "holdUntilChecked" not in plain["config"]
        for g in (held, plain):
            _ok(await c.post(f"/v1/guardrails/{g['id']}/publish-requests", json={"version": 1}), 201)
        pins = [{"guardrailId": g["id"], "version": 1} for g in (held, plain)]
        agent = _ok(await c.patch(f"/v1/agents/{ADVISOR}", json={"guardrailPins": pins}))
        _ok(await c.post(f"/v1/agents/{ADVISOR}/publish-requests", json={"version": agent["version"]}), 201)
        served = cast(Any, c)._transport.app.state.runtime.catalog.agent(ADVISOR)
        assert sorted((r.guardrail_id == held["id"], r.hold) for r in served.guardrails) == [
            (False, False),
            (True, True),
        ]
        off = _ok(await c.patch(f"/v1/guardrails/{held['id']}", json={"holdUntilChecked": False}))
        assert "holdUntilChecked" not in off["versions"][0]["config"], off["versions"][0]


def _blocking_model() -> FunctionModel:
    """Blocks a question about shares at the question check and answers anything else."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        last = messages[-1]
        prompt = (
            " ".join(str(p.content) for p in last.parts if isinstance(p, UserPromptPart))
            if isinstance(last, ModelRequest)
            else ""
        )
        if prompt.startswith("Blocked topics:"):
            topic = "investment advice" if "shares" in prompt.split("Message:", 1)[-1] else "none"
            return ModelResponse(parts=[ToolCallPart("final_result", {"topic": topic, "reason": "test"})])
        return ModelResponse(parts=[TextPart("The wire fee is 25.00.")])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        for part in respond(messages, info).parts:
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                yield {0: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args))}

    return FunctionModel(respond, stream_function=stream)


async def test_a_test_turn_refused_on_its_question_names_the_rule_and_claims_no_steps(tmp_path: Path) -> None:
    # agent-testing-2: a refused test turn read like an answered one ("searched", "loaded skill") and never named the
    # rule that stopped it.
    async with _app(str(tmp_path / "db.sqlite")) as c:
        g = await _published(c)
        agent = _ok(await _pin(c, g["id"], 1))
        _ok(await c.post(f"/v1/agents/{ADVISOR}/publish-requests", json={"version": agent["version"]}), 201)
        rt = cast(Any, c)._transport.app.state.runtime
        rt.ports = replace(rt.ports, model=_blocking_model(), models=None)
        t = _ok(await c.post(f"/v1/agents/{ADVISOR}/test", json={"message": "Should my client buy Northfield shares?"}))
        assert t["blockedBy"] == {"name": RULE["name"], "topic": "investment advice", "when": "before"}, t
        assert (t["reply"], t["searched"], t["skills"], t["citations"]) == (RULE["message"], False, [], []), t
        answered = _ok(await c.post(f"/v1/agents/{ADVISOR}/test", json={"message": "What is the wire fee?"}))
        assert "blockedBy" not in answered and answered["reply"] == "The wire fee is 25.00.", answered
