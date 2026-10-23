"""The Ops tools (c-469), by failure mode: a tool reads a record of a team the person is not in; the model passes a
person, email or team to widen a read; the agent is offered a workflow the person may not start; an unattended turn
uses the tools as nobody; an agent other than the team's default is offered them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from ops_agents.api import ops_tools
from ops_agents.api.agent_registry import registry
from ops_agents.api.auth import Principal
from ops_agents.api.child_runs import acting_for
from ops_agents.api.ops_tools import TOOLS, OpsReads, declared_args, ensure_ops_assistant
from ops_agents.store.cases import CaseStore
from ops_store.isolation import scope
from tests.api.test_action_roles import ADMIN, VIEWER
from tests.api.test_team_default_agent import URL, Stack, say, stack, start, viewer  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import TENANT

CARD_DISPUTE = json.loads((Path(__file__).parents[4] / "scripts/demo/workflows/card_dispute_intake.json").read_text())


def builder() -> Principal:
    return Principal(
        name="jane",
        email="jane@harborpine.example",
        team_id="team_ops",
        tenant_id=TENANT,
        team_ids=("team_ops",),
        role="builder",
        roles={"team_ops": "builder"},
    )


async def opened(stack_: Stack, team: str, subject: str) -> str:
    _, rt = stack_
    with scope(TENANT, team):
        case = await CaseStore(rt.db).open(
            team_id=team, subject=subject, priority="normal", by="seed@harborpine.example"
        )
    return str(case.case["id"])


def ids(outcome: Any) -> list[str]:
    return [c["id"] for c in outcome.output["cards"]]


async def test_a_tool_reads_only_the_persons_own_team_and_ignores_a_team_or_email_from_the_model(stack: Stack) -> None:  # noqa: F811 - the shared fixture
    _, rt = stack
    ours = await opened(stack, "team_ops", "Duplicate card charge (ops)")
    theirs = await opened(stack, "team_fraud", "Duplicate card charge (fraud)")
    ops = OpsReads(rt)
    with scope(TENANT, "team_ops"), acting_for(viewer()):
        found = await ops.run("find_cases", {"search": "Duplicate card charge"})
        assert found.ok and ids(found) == [ours], found.output
        other = await ops.run("get_case", {"caseId": theirs})
        assert not other.ok and theirs in other.output["error"], "another team's case is not found"
        widened = await ops.run(
            "find_cases", {"search": "Duplicate card charge", "teamId": "team_fraud", "team": "team_fraud"}
        )
        assert ids(widened) == [ours], "a team the model names changes nothing"
        named = await ops.run("my_human_tasks", {"which": "mine", "email": "maya@harborpine.example", "person": "maya"})
        plain = await ops.run("my_human_tasks", {"which": "mine"})
        assert named.output == plain.output, "an email or person the model names changes nothing"
    assert declared_args("my_human_tasks", {"which": "mine", "email": "x@y", "teamId": "t"}) == {"which": "mine"}


async def test_the_agent_is_not_offered_a_workflow_the_person_may_not_start(
    stack: Stack,  # noqa: F811 - the shared fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, rt = stack
    row = {"workflow_id": CARD_DISPUTE["id"], "team_id": "team_ops", "definition": CARD_DISPUTE}

    async def workflows(_rt: Any) -> list[dict[str, Any]]:
        return [row]

    monkeypatch.setattr(ops_tools, "engine_workflows", workflows)
    ops = OpsReads(rt)
    with scope(TENANT, "team_ops"):
        with acting_for(builder()):
            may = await ops.run("list_startable_workflows", {})
            form = await ops.run("start_workflow_form", {"workflowId": CARD_DISPUTE["id"]})
        with acting_for(viewer()):
            may_not = await ops.run("list_startable_workflows", {})
            refused = await ops.run("start_workflow_form", {"workflowId": CARD_DISPUTE["id"]})
    assert CARD_DISPUTE["id"] in may.output["summary"], may.output
    assert form.ok and form.output["cards"] == [{"type": "start", "id": CARD_DISPUTE["id"]}], form.output
    assert CARD_DISPUTE["id"] not in may_not.output["summary"], "a viewer may not run workflows, so none is offered"
    assert not refused.ok, refused.output


async def test_only_the_team_default_is_offered_the_tools_and_never_without_a_person(stack: Stack) -> None:  # noqa: F811 - the shared fixture
    c, rt = stack
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    thread = (await start(c, VIEWER))["id"]
    ops = OpsReads(rt)
    with scope(TENANT, "team_ops"):
        with acting_for(viewer()):
            assert {g.name for g in await ops.offers_in("ag_branch", thread)} == set(TOOLS), "the default gets them all"
            assert all(g.access == "read" for g in await ops.offers_in("ag_branch", thread)), (
                "every Ops tool only reads"
            )
            assert await ops.offers_in("ag_dispute", thread) == [], "an agent that is not the default gets none"
        assert await ops.offers_in("ag_branch", thread) == [], "an unattended turn is offered none"
        nobody = await ops.run("find_cases", {"search": "x"})
        assert not nobody.ok, "and calling one as nobody is refused"


async def test_a_card_is_filled_from_its_record_as_the_reader_and_says_so_when_out_of_reach(stack: Stack) -> None:  # noqa: F811 - the shared fixture
    c, _ = stack
    ours = await opened(stack, "team_ops", "Charged twice at Northwind Travel")
    theirs = await opened(stack, "team_fraud", "Card skimmed at a fuel pump")
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    thread = (await start(c, VIEWER))["id"]
    for case in (ours, theirs):
        events = await say(c, thread, f'call get_case {{"caseId": "{case}"}}', VIEWER)
        assert any(e.get("type") == "tool_end" for e in events), events
    messages = cast(
        list[dict[str, Any]], (await c.get(f"/v1/chat/threads/{thread}", headers=VIEWER)).json()["data"]["messages"]
    )
    calls = [cast(dict[str, Any], t) for m in messages for t in cast(list[Any], m.get("toolCalls") or [])]
    got = {str(t["input"]["caseId"]): t for t in calls if t["name"] == "get_case"}
    filled = cast(list[dict[str, Any]], got[ours]["output"]["cards"])
    assert filled[0]["type"] == "case" and filled[0]["view"]["subject"] == "Charged twice at Northwind Travel", filled
    theirs_out = cast(dict[str, Any], got[theirs]["output"])
    theirs_cards = cast(list[dict[str, Any]], theirs_out.get("cards") or [])
    assert not theirs_cards or theirs_cards[0].get("missing"), "another team's case is never drawn"


async def test_a_team_with_no_default_gets_one_ops_assistant_and_the_tools_follow_the_default(
    stack: Stack,  # noqa: F811 - the shared fixture
) -> None:
    c, rt = stack
    with scope(TENANT, "team_ops"):
        first_made = await ensure_ops_assistant(rt, "team_ops")
        # A second first chat in another process: its catalogue has not served the assistant yet, so it inserts again,
        # meets the first's row and serves it instead of failing.
        rt.catalog.drop_agent("ag_ops_team_ops")
        second_made = await ensure_ops_assistant(rt, "team_ops")
        rows = [r for r in await registry(rt).rows() if r["id"] == "ag_ops_team_ops"]
    assert first_made.id == second_made.id == "ag_ops_team_ops", "two first chats make one assistant"
    assert len(rows) == 1 and rows[0]["team_id"] == "team_ops", rows
    first = (await start(c, VIEWER))["id"]
    ops = OpsReads(rt)
    with scope(TENANT, "team_ops"), acting_for(viewer()):
        assert {g.name for g in await ops.offers_in("ag_ops_team_ops", first)} == set(TOOLS), "the default gets them"
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    with scope(TENANT, "team_ops"), acting_for(viewer()):
        assert await ops.offers_in("ag_ops_team_ops", first) == [], "a team admin's default takes the tools over"
        assert {g.name for g in await ops.offers_in("ag_branch", first)} == set(TOOLS)


async def test_a_call_missing_a_required_argument_is_refused_not_a_failed_turn(stack: Stack) -> None:  # noqa: F811 - the shared fixture
    _, rt = stack
    with scope(TENANT, "team_ops"), acting_for(viewer()):
        refused = await OpsReads(rt).run("get_run", {})
    assert not refused.ok and "runId" in refused.output["error"], refused.output
