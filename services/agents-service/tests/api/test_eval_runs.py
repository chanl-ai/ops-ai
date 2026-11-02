"""POST /v1/agents/{id}/eval-runs: empty 422, unknown agent 404, unknown check 422, pass, fail, summary."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from ops_agents.domain.evals import (
    CASES_EMPTY_CODE,
    CHECK_CALLS_TOOL,
    CHECK_REPLY_CONTAINS,
    CHECK_STATUS_FAIL,
    CHECK_STATUS_PASS,
    CHECK_UNKNOWN_CODE,
    EVAL_RUN_PREFIX,
    EVAL_STATUS_COMPLETE,
)

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
