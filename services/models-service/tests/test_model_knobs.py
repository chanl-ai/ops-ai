"""The knobs an alias offers and the knobs a call carries, by failure mode: the knobs reply lists a knob the alias's
model does not take, or leaves out its catalog default and range; and a call reaches the provider with a knob the
model does not take or a value outside the model's range. The provider is a fake; the catalog is the committed
snapshot (Claude Haiku 4.5 takes temperature 0 to 1, top p, top k, a thinking budget of 0 or 1,024 up, and answers of
up to 64,000 tokens, and no thinking effort)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from ops_models.app import create_models_app
from ops_models.catalog import CATALOG_DIR, Catalog
from ops_service_kit.contract import response_checker

from .conftest import LOCAL, SERVICE, Models

HAIKU = "claude-haiku-4-5"


async def _rig(models: Models, sent: list[dict[str, Any]]) -> tuple[httpx.AsyncClient, Models]:
    def provider(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        answer: dict[str, Any] = {"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}}
        return httpx.Response(200, json=answer)

    app = create_models_app(models.engine, upstream=httpx.AsyncClient(transport=httpx.MockTransport(provider)))
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(
        transport=transport, base_url="http://models", event_hooks={"response": [response_checker(app)]}
    )
    return client, Models(client, models.engine, app)


async def _alias(c: httpx.AsyncClient, kind: str, model: str, **conn: str) -> str:
    tag = f"knobs-{uuid4().hex[:8]}"
    made = await c.post("/v1/models/providers", json={"name": tag, "type": kind, **conn}, headers=SERVICE)
    assert made.status_code == 201, made.text
    version = {"providerId": made.json()["data"]["id"], "modelId": model, "clearedSensitivity": "internal"}
    assert (await c.post("/v1/models/aliases", json={"name": tag, **version}, headers=SERVICE)).status_code == 201
    return tag


async def test_the_knobs_reply_lists_only_what_the_model_takes_with_its_catalog_defaults(models: Models) -> None:
    c = models.client
    haiku = await _alias(c, "anthropic", HAIKU)
    custom = await _alias(c, "openai-compatible", "llama-3-70b", baseUrl="http://vllm.internal/v1")
    catalogued = (await c.get(f"/v1/models/aliases/{haiku}/knobs", headers=SERVICE)).json()["data"]
    unknown = (await c.get(f"/v1/models/aliases/{custom}/knobs", headers=SERVICE)).json()["data"]
    listed = (await c.get("/v1/models/aliases", params={"ids": haiku}, headers=SERVICE)).json()["data"]["data"]
    assert [a["providerName"] for a in listed] == [haiku], "an alias names its connection, made under the same tag"

    knobs = catalogued["knobs"]["properties"]
    assert set(knobs) == {"temperature", "top_p", "top_k", "thinking_budget", "max_tokens"}, knobs
    assert (knobs["temperature"]["default"], knobs["temperature"]["maximum"]) == (1, 1), knobs["temperature"]
    assert (knobs["max_tokens"]["default"], knobs["max_tokens"]["maximum"]) == (8192, 64000), knobs["max_tokens"]
    assert knobs["thinking_budget"]["x-minimum-on"] == 1024 and catalogued["catalogued"] is True, knobs
    loose = unknown["knobs"]["properties"]
    assert set(loose) == {"temperature", "top_p", "max_tokens"} and not unknown["catalogued"], unknown
    assert all("default" not in k and "maximum" not in k for k in loose.values()), loose


async def test_a_call_reaches_the_provider_fitted_to_the_model(models: Models) -> None:
    sent: list[dict[str, Any]] = []
    c, on_app = await _rig(models, sent)
    async with c:
        haiku = await _alias(c, "anthropic", HAIKU, baseUrl="http://up/v1")
        _, secret = await on_app.key(budget="5")
        body = {
            "model": haiku,
            "messages": [{"role": "user", "content": "Summarise claim CLM-77"}],
            "temperature": 1.7,
            "top_k": 40,
            "max_tokens": 999999,
            "reasoning_effort": "max",
            # By knob name, as agents-service sends a saved setting.
            "thinking_budget": 100,
            "parallel_tool_calls": False,
        }
        r = await c.post(
            "/v1/models/chat/completions", json=body, headers={"Authorization": f"Bearer {secret}", **LOCAL}
        )
    assert r.status_code == 200, r.text
    got = {k: sent[0].get(k) for k in ("temperature", "top_k", "max_tokens", "reasoning_effort", "thinking")}
    assert got == {
        "temperature": 1.0,
        "top_k": 40,
        "max_tokens": 64000,
        "reasoning_effort": None,
        "thinking": {"type": "enabled", "budget_tokens": 1024},
    }, sent[0]
    assert sent[0]["parallel_tool_calls"] is False, "a setting that is not a knob is passed on as sent"


def test_an_edit_to_the_knob_table_changes_the_model_knobs(tmp_path: Path) -> None:
    """The ranges, defaults and knobs each provider takes are the knob table's, read when the catalog loads: the
    snapshot holds only each model's facts."""
    shutil.copy(CATALOG_DIR / "models.json", tmp_path / "models.json")
    table = json.loads((CATALOG_DIR / "knobs.json").read_text())
    anthropic = table["providers"]["anthropic"]
    anthropic["ranges"]["temperature"] = {"minimum": 0, "maximum": 0.8, "default": 0.5}
    anthropic["takes"].remove("top_k")
    (tmp_path / "knobs.json").write_text(json.dumps(table))

    knobs = Catalog.load(tmp_path).knob_schema("anthropic", HAIKU)["properties"]
    assert isinstance(knobs, dict) and "top_k" not in knobs, knobs
    assert knobs["temperature"] == {
        "type": "number",
        "title": "Temperature",
        "description": "Lower is steadier, higher is more varied.",
        "minimum": 0.0,
        "maximum": 0.8,
        "default": 0.5,
    }, knobs["temperature"]


@pytest.mark.parametrize(
    ("kind", "model", "field"),
    [
        ("openai", "gpt-5.2", "max_completion_tokens"),
        ("azure", "claude-fable-5", "max_completion_tokens"),
        ("anthropic", HAIKU, "max_tokens"),
        ("google", "gemini-2.5-flash-lite", "max_tokens"),
        ("amazon-bedrock", "amazon.nova-lite-v1:0", "max_tokens"),
        (None, "llama-3.1-8b-instruct", "max_tokens"),
    ],
)
@pytest.mark.parametrize("sent", ["max_tokens", "max_completion_tokens"])
def test_an_output_limit_reaches_each_provider_in_the_field_it_honours(
    kind: str | None, model: str, field: str, sent: str
) -> None:
    """A caller names the limit either way; OpenAI's reasoning models refuse `max_tokens`, and Anthropic, Gemini,
    Bedrock and most self-hosted OpenAI-compatible servers read only `max_tokens`."""
    fitted = Catalog.load().fit({"model": "a", sent: 900}, kind, model)
    limits = {k: v for k, v in fitted.items() if k in ("max_tokens", "max_completion_tokens")}
    assert limits == {field: 900}, fitted
