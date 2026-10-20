"""A turn runs on the model its agent's alias names, and the models-service source never retries a refusal."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx2
import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.models import ModelsServiceModels
from ops_agent_kernel.ports import KernelPorts
from ops_agent_kernel.types import AgentSettings, PromptFragment, TurnRequest

from .test_kernel import FixedKnowledge, RecordingTools


def _says(text: str) -> FunctionModel:
    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        yield text

    return FunctionModel(stream_function=stream)


class Aliases:
    def model_for(self, alias: str) -> Model:
        return _says(f"ran on {alias}")


async def test_a_turn_runs_on_its_agents_alias() -> None:
    settings = AgentSettings("ag_fraud", 1, [PromptFragment("You help.")], "bank-reasoning")
    ports = KernelPorts(_says("ran on the runtime model"), RecordingTools(), FixedKnowledge([]), models=Aliases())
    events = [e async for e in run_turn(TurnRequest("t1", "th1", settings, [], user_turn="hello"), ports)]
    finished = events[-1]
    assert isinstance(finished, TurnFinished)
    assert finished.result.text == "ran on bank-reasoning"


async def test_the_models_service_source_sends_one_request_per_refusal() -> None:
    seen: list[httpx2.Request] = []

    def refuse(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        error = {"code": "rate_limited", "message": "over", "status": 429, "requestId": "req_1"}
        return httpx2.Response(429, json={"success": False, "error": error})

    source = ModelsServiceModels(
        "http://models", "mk_test", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(refuse))
    )
    model = source.model_for("bank-standard")
    assert source.model_for("bank-standard") is model
    request = ModelRequest(parts=[UserPromptPart("hi")])
    with pytest.raises(ModelHTTPError) as refused:
        await model.request([request], None, ModelRequestParameters())
    assert refused.value.status_code == 429
    assert len(seen) == 1
    assert seen[0].url.path == "/v1/models/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer mk_test"
    assert json.loads(seen[0].content)["model"] == "bank-standard"
