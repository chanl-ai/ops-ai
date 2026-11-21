"""POST /v1/agents/{id}/eval-runs: empty 422, unknown agent 404, unknown check 422, pass, fail, summary, and a kept
run's cost stored as 0 while its turns and judge spent tokens."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from ops_agent_kernel import judge
from ops_agents.domain.evals import (
    CASES_EMPTY_CODE,
    CHECK_CALLS_TOOL,
    CHECK_REPLY_CONTAINS,
    CHECK_STATUS_FAIL,
    CHECK_STATUS_PASS,
    CHECK_UNKNOWN_CODE,
    EVAL_RUN_PREFIX,
    EVAL_STATUS_COMPLETE,
    judge_evidence,
    turn_from_test,
)
from ops_metering import PriceTable, Usage, cost
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, empty_engine, scripted_model, started

AGENT = "ag_fraud"


def _case(name: str, message: str, *checks: dict[str, str]) -> dict[str, Any]:
    return {"name": name, "input": message, "checks": list(checks)}


async def test_empty_cases_are_422(client: AsyncClient) -> None:
    res = await client.post(f"/v1/agents/{AGENT}/eval-runs", json={"cases": []})
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == CASES_EMPTY_CODE


async def test_unknown_agent_is_404(client: AsyncClient) -> None:
    res = await client.post(
        "/v1/agents/ag_missing/eval-runs",
        json={"cases": [_case("x", "Hello", {"type": CHECK_REPLY_CONTAINS, "text": "Hello"})]},
    )
    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "not_found"


async def test_unknown_check_type_is_422(client: AsyncClient) -> None:
    res = await client.post(
        f"/v1/agents/{AGENT}/eval-runs",
        json={"cases": [_case("x", "Hello", {"type": "rubric", "text": "kind"})]},
    )
    assert res.status_code == 422, res.text
    err = res.json()["error"]
    assert err["code"] == CHECK_UNKNOWN_CODE
    assert err["details"]["type"] == "rubric"


async def test_one_pass_one_fail_and_summary_counts(client: AsyncClient) -> None:
    res = await client.post(
        f"/v1/agents/{AGENT}/eval-runs",
        json={
            "cases": [
                _case("says-not-found", "Hello", {"type": CHECK_REPLY_CONTAINS, "text": "could not find"}),
                _case("calls-lookup", "Hello", {"type": CHECK_CALLS_TOOL, "tool": "lookup_account"}),
            ]
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True
    data = body["data"]
    assert data["id"].startswith(f"{EVAL_RUN_PREFIX}_")
    assert data["agentId"] == AGENT
    assert data["status"] == EVAL_STATUS_COMPLETE
    assert data["summary"] == {"passed": 1, "total": 2, "regressions": 0}
    assert len(data["results"]) == 2
    first, second = data["results"]
    assert first["caseName"] == "says-not-found"
    assert first["draft"]["status"] == CHECK_STATUS_PASS
    assert first["draft"]["reply"]
    assert first["draft"]["checks"][0]["status"] == CHECK_STATUS_PASS
    assert first["live"] is None
    assert first["regression"] is False
    assert isinstance(first["draft"]["latencyMs"], int)
    assert second["caseName"] == "calls-lookup"
    assert second["draft"]["status"] == CHECK_STATUS_FAIL
    assert second["draft"]["checks"][0]["status"] == CHECK_STATUS_FAIL


async def test_a_kept_run_stores_the_priced_usage_of_its_turns_and_judge(
    graph_models: FakeGraphModels, database_url: str
) -> None:
    rubric = "The reply says \u201ccould not find\u201d."
    case = _case("judged", "Hello", {"type": "judge", "rubric": rubric})
    async with empty_engine(database_url) as engine:
        probe = Settings(database_url=database_url, seed_dir=SEED)
        async with started(engine, probe, graph_models) as (_, c):
            alias = (await c.post(f"/v1/agents/{AGENT}/test", json={"message": "Hello"})).json()["data"]["model"]
        prices = {alias: {"input": "1000", "output": "3000"}}
        settings = Settings(database_url=database_url, seed_dir=SEED, prices=prices)
        async with started(engine, settings, graph_models, checked=True) as (_, c):
            turn = (await c.post(f"/v1/agents/{AGENT}/test", json={"message": "Hello"})).json()["data"]
            assert (await c.put(f"/v1/agents/{AGENT}/eval-cases", json={"cases": [case]})).status_code == 200
            ran = (await c.post(f"/v1/agents/{AGENT}/eval-runs")).json()["data"]
            stored = (await c.get(f"/v1/eval-runs/{ran['id']}")).json()["data"]
            listed = (await c.get(f"/v1/agents/{AGENT}/eval-runs")).json()["data"]["data"][0]
    found = await judge.verdict(scripted_model(), rubric, judge_evidence(turn_from_test(turn)))
    assert found.passed is True
    spent = Usage(
        turn["usage"]["inputTokens"] + found.usage.input_tokens,
        turn["usage"]["outputTokens"] + found.usage.output_tokens,
    )
    expected = float(cost(spent, PriceTable.parse(prices).price(alias)))
    assert stored["results"][0]["draft"]["checks"][0]["status"] == CHECK_STATUS_PASS
    assert stored["costUsd"] > 0
    assert stored["costUsd"] == expected
    assert stored["unpriced"] is False
    # A list row leaves the case results to the single read.
    assert "results" not in listed
    assert listed["id"] == stored["id"] and listed["unpriced"] is False


async def test_only_a_case_with_a_judge_check_reads_its_judge_as_unpriced(
    graph_models: FakeGraphModels, database_url: str
) -> None:
    judged = _case("judged", "Hello", {"type": "judge", "rubric": "The reply says it could not find the account."})
    plain = _case("plain", "Hello", {"type": CHECK_REPLY_CONTAINS, "text": "could not find"})
    settings = Settings(database_url=database_url, seed_dir=SEED)
    async with empty_engine(database_url) as engine, started(engine, settings, graph_models) as (_, c):
        assert (await c.put(f"/v1/agents/{AGENT}/eval-cases", json={"cases": [judged, plain]})).status_code == 200
        ran = (await c.post(f"/v1/agents/{AGENT}/eval-runs")).json()["data"]
        stored = (await c.get(f"/v1/eval-runs/{ran['id']}")).json()["data"]
    by_name = {r["caseName"]: r for r in stored["results"]}
    assert [by_name[n]["unpriced"] for n in ("judged", "plain")] == [True, True], "no alias is priced here"
    assert [by_name[n]["judgeUnpriced"] for n in ("judged", "plain")] == [True, False], by_name
