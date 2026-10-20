"""A workflow AI step's answer for an agent or an outside caller (tick 30: the four AI steps had no API), by failure
mode: the route answers differently from a step; someone who may not run workflows gets an answer; a team with AI steps
off gets one; settings the step's type refuses are run anyway."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, ClassVar, cast

import pytest
from httpx import AsyncClient
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo

from ops_documents_client import DocumentsClient
from tests.conftest import structured
from tests.engine.test_lifecycle_rights import BUILDER, VIEWER, person
from tests.unit.test_agent_step_port import _streamed  # pyright: ignore[reportPrivateUsage]

from .role_app import ok, role_app

SETTINGS = {"categories": [{"name": "refund", "description": "Asks for money back"}, {"name": "fraud"}]}


class Policies:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    async def value(self, key: str) -> Any:
        return self.values.get(key, {})


def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    return structured(info, {"category": "refund", "confidence": 0.9, "reason": "Wants the fee back."})


@pytest.fixture
async def c() -> AsyncIterator[AsyncClient]:
    async with role_app(_streamed(answer)) as client:
        yield client


def policies(c: AsyncClient, values: dict[str, Any]) -> None:
    app = cast(Any, c)._transport.app
    app.state.runtime.policies = Policies(values)


async def test_a_builder_gets_the_steps_answer_and_the_port_it_leaves_by(c: AsyncClient) -> None:
    policies(c, {"aiSteps": {"team_ops": True}})
    body = {"text": "Please refund the overdraft fee.", "settings": SETTINGS}
    got = ok(await c.post("/v1/ai-steps/classify", json=body, headers=BUILDER))
    assert got == {
        "port": "refund",
        "output": {"category": "refund", "confidence": 0.9, "reason": "Wants the fee back."},
    }


async def test_someone_who_may_not_run_workflows_gets_no_answer(c: AsyncClient) -> None:
    policies(c, {"aiSteps": {"team_ops": True}})
    res = await c.post("/v1/ai-steps/classify", json={"text": "x", "settings": SETTINGS}, headers=VIEWER)
    assert res.status_code == 403, res.text


async def test_a_team_with_ai_steps_off_gets_no_answer(c: AsyncClient) -> None:
    policies(c, {"aiSteps": {"team_other": True}})
    res = await c.post("/v1/ai-steps/classify", json={"text": "x", "settings": SETTINGS}, headers=BUILDER)
    assert (res.status_code, res.json()["error"]["code"]) == (422, "ai_steps_off"), res.text


async def test_settings_the_steps_type_refuses_are_not_run(c: AsyncClient) -> None:
    policies(c, {"aiSteps": {"team_ops": True}})
    res = await c.post(
        "/v1/ai-steps/classify", json={"text": "x", "settings": {"categories": "refund"}}, headers=BUILDER
    )
    assert (res.status_code, res.json()["error"]["code"]) == (422, "invalid_settings"), res.text


async def test_a_text_past_the_bound_is_not_run(c: AsyncClient) -> None:
    """tick 31: the route had no limit, so one outside call could send any amount of text to the model."""
    policies(c, {"aiSteps": {"team_ops": True}})
    rt = cast(Any, c)._transport.app.state.runtime
    body = {"text": "x" * (rt.settings.ai_step_max_text_chars + 1), "settings": SETTINGS}
    res = await c.post("/v1/ai-steps/classify", json=body, headers=BUILDER)
    assert (res.status_code, res.json()["error"]["code"]) == (422, "text_too_long"), res.text


class Documents:
    """documents-service's client as the route uses it: one document type, read as the team it is asked for."""

    asked: ClassVar[list[str]] = []

    async def document_type(self, tenant: str, team: str, type_id: str) -> dict[str, Any]:
        Documents.asked.append(team)
        return {"versions": [{"version": 1, "fields": [{"key": "amount", "label": "Amount", "type": "money"}]}]}

    async def aclose(self) -> None:
        return None


def amount(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    # Matches the answer schema only when it names the type's fields, that is, when the route looked them up.
    return structured(info, {"amount": 3250.0})


async def test_a_document_types_fields_are_read_as_the_callers_team(monkeypatch: pytest.MonkeyPatch) -> None:
    """tick 31: the route skipped the documentType lookup a step makes, so the two answered differently."""

    def documents(*args: Any, **kwargs: Any) -> Documents:
        return Documents()

    monkeypatch.setattr(DocumentsClient, "from_settings", documents)
    async with role_app(_streamed(amount)) as client:
        rt = cast(Any, client)._transport.app.state.runtime
        rt.settings = rt.settings.model_copy(update={"documents_url": "http://documents"})
        policies(client, {"aiSteps": {"team_ops": True}})
        body = {"text": "Levy of 3,250.00", "settings": {"documentType": {"id": "levy_notice"}}}
        got = ok(await client.post("/v1/ai-steps/extract-text", json=body, headers=BUILDER))
    assert (got["output"], Documents.asked) == ({"amount": 3250.0}, ["team_ops"]), got


async def test_a_team_past_its_calls_a_minute_is_refused_before_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """tick 32: the route had no rate limit, so one team's caller could spend the service's whole model key."""
    from ops_agents.api.routers import ai_steps  # noqa: PLC0415
    from ops_agents.api.widget_sessions import RateLimit  # noqa: PLC0415

    monkeypatch.setattr(ai_steps, "calls", RateLimit())
    asked: list[int] = []

    def counted(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        asked.append(1)
        return answer(messages, info)

    async with role_app(_streamed(counted)) as client:
        policies(client, {"aiSteps": {"team_ops": True, "team_risk": True}})
        rt = cast(Any, client)._transport.app.state.runtime
        rt.settings = rt.settings.model_copy(update={"ai_step_calls_per_minute": 2})
        body = {"text": "Please refund the overdraft fee.", "settings": SETTINGS}
        for _ in range(2):
            ok(await client.post("/v1/ai-steps/classify", json=body, headers=BUILDER))
        res = await client.post("/v1/ai-steps/classify", json=body, headers=BUILDER)
        assert (res.status_code, res.json()["error"]["code"]) == (429, "too_many_requests"), res.text
        assert len(asked) == 2, "the refused call reached the model"
        ok(await client.post("/v1/ai-steps/classify", json=body, headers=person("rita", "team_risk", "builder")))
