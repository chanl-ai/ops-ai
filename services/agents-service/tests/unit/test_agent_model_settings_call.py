"""An agent version's saved model settings reach the model call: through the version's spec, the catalogue's turn
settings and the kernel, into the OpenAI-shaped request models-service receives, each under its knob name. The
models-service end is faked at the HTTP edge, so the assertion reads the body as it would arrive."""

from __future__ import annotations

import json
from typing import Any, cast

import httpx
from openai import AsyncOpenAI

from ops_agent_kernel.contract import ModelEndpoint
from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts
from ops_agent_kernel.types import TurnRequest
from ops_agents.activities.catalog import load_catalog
from ops_agents.api.agent_registry import definition_of
from ops_service_kit.http import Json
from tests.conftest import SEED
from tests.unit.test_skill_steps_kernel import LEGACY_SPEC, NoKnowledge, Systems

ANSWER = {
    "id": "chatcmpl_1",
    "object": "chat.completion",
    "created": 1,
    "model": "bank-standard",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Nine."}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
}


async def test_saved_model_settings_reach_the_request_models_service_receives() -> None:
    sent: list[dict[str, Any]] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=ANSWER)

    saved: Json = {"temperature": 0.3, "top_k": 40, "thinking_budget": 2048, "max_tokens": 512}
    spec: Json = {**LEGACY_SPEC, "skillPins": [], "modelSettings": saved}
    settings = load_catalog(SEED).settings_for(definition_of("ag_branch", 4, spec), "bank-standard")
    client = AsyncOpenAI(
        base_url="http://models/v1",
        api_key="mk",
        http_client=cast(Any, httpx.AsyncClient(transport=httpx.MockTransport(gateway))),
    )
    model = ModelEndpoint(client, "bank-standard")
    ports = KernelPorts(model=model, tools=Systems(), knowledge=NoKnowledge())
    req = TurnRequest("t1", "th1", settings, [], user_turn="When does the branch open?")
    events = [e async for e in run_turn(req, ports)]
    assert isinstance(events[-1], TurnFinished), events[-1]

    body = sent[0]
    # By knob name: models-service maps each to its provider's field (tests/test_model_knobs.py there).
    assert {k: body.get(k) for k in saved} == saved, body
