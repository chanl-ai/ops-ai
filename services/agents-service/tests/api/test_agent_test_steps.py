"""What a test reply says it did, by failure mode: a citation that does not name its knowledge base and page; a
gated call that reads as a success; a read-only tool listed as pausing, or a pausing write tool missing; a reply that
searched nothing and called nothing saying nothing about it."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from ops_agents.api.deps import Runtime
from ops_agents.domain.evals import EvalCase, EvalCheck, score_case, turn_from_test
from tests.api.test_agent_page_backed import (  # noqa: F401  # a fixture
    WIRE,  # pyright: ignore[reportUnusedImport]
    stack,  # pyright: ignore[reportUnusedImport]
)


async def turn(client: AsyncClient, agent: str, message: str) -> dict[str, Any]:
    res = await client.post(f"/v1/agents/{agent}/test", json={"message": message})
    assert res.status_code == 200, res.text
    return res.json()["data"]


async def test_a_citation_names_its_knowledge_base_and_the_words_cited(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, _ = stack
    t = await turn(client, "ag_fraud", "What is the daily wire limit?")
    assert t["knowledgeBases"], "the bases the reply could search are named"
    cited = t["citations"]
    assert cited and all(c["kbId"] and c["kbName"] and c["quote"] for c in cited), cited
    assert {c["kbId"] for c in cited} <= {k["id"] for k in t["knowledgeBases"]}, (cited, t["knowledgeBases"])


async def test_a_gated_call_says_it_stopped_for_a_review(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, _ = stack
    t = await turn(client, "ag_fraud", WIRE)
    calls = {c["name"]: c["status"] for c in t["toolCalls"]}
    assert calls.get("place_wire_hold") == "gated", t["toolCalls"]
    assert t["wouldPause"]["tool"] == "place_wire_hold"
    # An eval reads this reply: the write paused and was not sent, and the turn planned before it, so a case that
    # expects a direct answer fails on it.
    seen = turn_from_test(t)
    paused = EvalCheck("pauses_on", tool="place_wire_hold")
    planned = EvalCase("hold", WIRE, (paused, EvalCheck("mode_in", modes=("direct", "plan"))))
    direct = EvalCase("hold", WIRE, (paused, EvalCheck("mode_in", modes=("direct",))))
    assert "plan" in t["modes"], t["modes"]
    assert (score_case(planned, seen).status, score_case(direct, seen).status) == ("pass", "fail"), seen


async def test_the_tools_that_pause_are_named_and_read_only_ones_are_not(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, _ = stack
    t = await turn(client, "ag_fraud", "Hello")
    held = {x["name"]: x for x in t["tools"]}
    assert held["place_wire_hold"]["pauses"] is True and held["place_wire_hold"]["gate"], held
    assert held["lookup_account"]["pauses"] is False and "gate" not in held["lookup_account"], held
    assert t["toolCalls"] == [] and t["citations"] == [], "a plain reply called and cited nothing, and says so"


async def test_a_test_naming_someone_to_run_as_is_refused_not_ignored(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    """Run as was removed, but the route still took a run-as id and ran as the caller anyway."""
    client, _ = stack
    res = await client.post("/v1/agents/ag_advisor/test", json={"message": "Hello", "runAsId": "per_teller"})
    assert (res.status_code, res.json()["error"]["code"]) == (400, "validation_failed"), res.text
