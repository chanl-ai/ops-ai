"""The eval judge, by failure mode: a judge that cannot answer (its call raises, or it answers outside its schema) and
the case passes anyway."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ops_agent_kernel import judge
from ops_agents.app.evals import parse_cases, run_eval
from ops_agents.domain.evals import CHECK_STATUS_FAIL
from ops_service_kit.http import Json
from ops_service_kit.narrow import json_list, json_object


def _raises(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    raise RuntimeError("provider down")


def _off_schema(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart("final_result", {"passed": "yes"})])


async def _turn(message: str, collections: tuple[str, ...]) -> Json:
    return {"reply": "We could not find that payee.", "toolCalls": [], "tookMs": 1, "model": "default"}


@pytest.mark.parametrize("respond", [_raises, _off_schema], ids=["raises", "off-schema"])
async def test_a_judge_that_cannot_answer_fails_the_check_with_a_reason(respond: Any) -> None:
    model = FunctionModel(respond)

    async def judged(rubric: str, evidence: str, alias: str) -> tuple[judge.Verdict, str]:
        return await judge.verdict(model, rubric, evidence), alias

    cases = parse_cases(
        [{"name": "no refund", "input": "Hi", "checks": [{"type": "judge", "rubric": "Promises no refund."}]}]
    )
    run = await run_eval("ag_x", cases, _turn, judge=judged)
    draft = json_object(json_object(json_list(run["results"])[0])["draft"])
    check = json_object(json_list(draft["checks"])[0])
    assert draft["status"] == CHECK_STATUS_FAIL
    assert check["status"] == CHECK_STATUS_FAIL
    assert str(check["reason"]).startswith("The judge did not answer")
