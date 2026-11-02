"""Azure OpenAI connections (c-605), by failure mode: the key sent as a bearer token, the deployment URL built wrong,
an api-version missing or too old to stream usage, the key echoed back, streamed usage not read or Azure's annotation
frames passed on, tool calls lost, and a resource answering from another region than the connection names going
unrecorded. Each runs models-service in process against the fake Azure in scripts/fake_openai, which answers as Azure
does: 401 to a bearer token on the deployment path, 404 without an api-version, and its own `x-ms-region` header."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import Header, Request

from ops_identity import Principal, current_tenant_caller
from ops_models.app import create_models_app
from ops_service_kit.contract import response_checker

from .conftest import SERVICE, Models

FAKE = Path(__file__).resolve().parents[1] / "scripts" / "fake_openai"
KEY = "azure-key-0123456789abcdef"
DEPLOYMENT = "claims-gpt4o"
ENDPOINT = "http://contoso-claims.openai.azure.example"


def _fake_module() -> ModuleType:
    if "fake_openai.app" in sys.modules:
        return sys.modules["fake_openai.app"]
    sys.path.insert(0, str(FAKE.parent))
    spec = importlib.util.spec_from_file_location("fake_openai.app", FAKE / "app.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Recording(httpx.AsyncBaseTransport):
    """Forwards to the fake Azure app and keeps each request, so a test reads the header and URL Azure received."""

    def __init__(self, app: Any, seen: list[httpx.Request]) -> None:
        self.inner = httpx.ASGITransport(app=app)
        self.seen = seen

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        return await self.inner.handle_async_request(request)


def _person(role: str) -> Any:
    """An account admin (admin of team_security) or a builder when no service token is sent."""

    async def caller(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        x_team_id: Annotated[str | None, Header()] = None,
    ) -> Principal:
        if authorization:
            return await current_tenant_caller(request, authorization=authorization, x_team_id=x_team_id)
        team = "team_security" if role == "admin" else "team_ops"
        return Principal(
            kind="person",
            sub=f"usr_{role}",
            email=f"{role}@bank.example",
            name=role,
            tenant_id="local",
            team_id=team,
            team_ids=[team],
            roles={team: role},
            scopes=[],
            auth_method="session",
        )

    return caller


@dataclass
class Azure:
    client: httpx.AsyncClient
    models: Models
    seen: list[httpx.Request] = field(default_factory=lambda: [])

    async def connect(self, api_version: str = "2024-10-21", region: str | None = "swedencentral", **extra: Any) -> str:
        body = {
            "name": f"azure-{uuid4().hex[:8]}",
            "type": "azure-openai",
            "baseUrl": ENDPOINT,
            "keyRef": "AZURE_CLAIMS",
            "apiVersion": api_version,
            "region": region,
            **extra,
        }
        r = await self.client.post("/v1/models/providers", json=body, headers=SERVICE)
        assert r.status_code == 201, r.text
        return str(r.json()["data"]["id"])

    async def alias(self, provider_id: str) -> str:
        name = f"claims-{uuid4().hex[:8]}"
        version = {"name": name, "providerId": provider_id, "modelId": DEPLOYMENT, "clearedSensitivity": "internal"}
        assert (await self.client.post("/v1/models/aliases", json=version, headers=SERVICE)).status_code == 201
        return name

    async def call(self, alias: str, *, stream: bool = False, tools: bool = False) -> httpx.Response:
        _, secret = await self.models.key(budget="5")
        body: dict[str, Any] = {
            "model": alias,
            "messages": [{"role": "user", "content": "call lookup_claim" if tools else "Summarise claim CLM-77"}],
            "stream": stream,
        }
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": "lookup_claim", "parameters": {}}}]
        return await self.client.post(
            "/v1/models/chat/completions", json=body, headers={"Authorization": f"Bearer {secret}"}
        )

    async def connection(self, provider_id: str) -> dict[str, Any]:
        rows = (await self.client.get("/v1/models/providers", headers=SERVICE)).json()["data"]
        return next(r for r in rows if r["id"] == provider_id)


async def _azure(models: Models, region: str = "Sweden Central", role: str = "admin") -> AsyncIterator[Azure]:
    fake = _fake_module()
    seen: list[httpx.Request] = []
    upstream = httpx.AsyncClient(
        transport=_Recording(fake.create_app(fake.Script(rules=[], models=[]), KEY, region), seen)
    )
    app = create_models_app(models.engine, provider_secrets={"AZURE_CLAIMS": KEY}, upstream=upstream)
    app.dependency_overrides[current_tenant_caller] = _person(role)
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://models", event_hooks=hooks
    ) as client:
        yield Azure(client, Models(client, models.engine, app), seen)


@pytest.fixture
async def azure(models: Models) -> AsyncIterator[Azure]:
    async for a in _azure(models):
        yield a


def _events(r: httpx.Response) -> list[dict[str, Any]]:
    lines = [ln.removeprefix("data: ") for ln in r.text.splitlines() if ln.startswith("data: ")]
    return [json.loads(ln) for ln in lines if ln != "[DONE]"]


async def test_key_goes_in_api_key_header(azure: Azure) -> None:
    r = await azure.call(await azure.alias(await azure.connect()))
    assert r.status_code == 200, r.text
    sent = azure.seen[-1].headers
    assert sent.get("api-key") == KEY and "authorization" not in sent, dict(sent)


async def test_deployment_url_built_from_endpoint(azure: Azure) -> None:
    dated = await azure.alias(await azure.connect("2024-10-21"))
    v1 = await azure.alias(await azure.connect("v1"))
    assert (await azure.call(dated)).status_code == 200
    on_dated = azure.seen[-1]
    assert (await azure.call(v1)).status_code == 200
    on_v1 = azure.seen[-1]
    assert on_dated.url.path == f"/openai/deployments/{DEPLOYMENT}/chat/completions", on_dated.url
    assert on_dated.url.params.get("api-version") == "2024-10-21"
    assert on_v1.url.path == "/openai/v1/chat/completions" and not on_v1.url.params, on_v1.url
    assert json.loads(on_v1.content)["model"] == DEPLOYMENT


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"apiVersion": None}, "apiVersion"),
        ({"apiVersion": "2024-06-01"}, "apiVersion"),
        ({"apiVersion": "latest"}, "apiVersion"),
        ({"baseUrl": f"{ENDPOINT}/openai/v1"}, "baseUrl"),
    ],
)
async def test_api_version_required_and_dated_at_least_2024_10_21(
    azure: Azure, changes: dict[str, Any], field: str
) -> None:
    body = {"name": f"azure-{uuid4().hex[:8]}", "type": "azure-openai", "baseUrl": ENDPOINT, "keyRef": "AZURE_CLAIMS"}
    body |= {"apiVersion": "2024-10-21", "region": "swedencentral"}
    r = await azure.client.post("/v1/models/providers", json=body | changes, headers=SERVICE)
    assert r.status_code == 400 and field in r.text, r.text
    # A rebind is held to the same rule as a create.
    pid = await azure.connect()
    moved = {"baseUrl": ENDPOINT, "keyRef": "AZURE_CLAIMS", "apiVersion": "2024-10-21", "region": "swedencentral"}
    rebind = await azure.client.put(f"/v1/models/providers/{pid}", json=moved | changes, headers=SERVICE)
    assert rebind.status_code == 400 and field in rebind.text, rebind.text


async def test_key_never_echoed(models: Models, caplog: pytest.LogCaptureFixture) -> None:
    # OpenAI's own 401 quotes the key it was sent; Azure's may too. Nothing of it may come back or reach a log.
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": f"Incorrect API key provided: {KEY}"}})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    app = create_models_app(models.engine, provider_secrets={"AZURE_CLAIMS": KEY}, upstream=upstream)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://models") as client:
        azure = Azure(client, Models(client, models.engine, app))
        pid = await azure.connect()
        alias = await azure.alias(pid)
        plain, streamed = await azure.call(alias), await azure.call(alias, stream=True)
        listed = await client.get("/v1/models/providers", headers=SERVICE)
        calls = await client.get("/v1/models/calls", params={"alias": alias}, headers=SERVICE)
    assert plain.status_code == 502 and streamed.status_code == 502
    for text in (plain.text, streamed.text, listed.text, calls.text, caplog.text):
        assert KEY not in text and KEY[:12] not in text
    assert "AZURE_CLAIMS" in listed.text, "the key's name is shown"


async def test_stream_usage_read_and_annotation_frames_dropped(azure: Azure) -> None:
    alias = await azure.alias(await azure.connect("v1"))
    r = await azure.call(alias, stream=True)
    assert r.status_code == 200, r.text
    events = _events(r)
    assert events[0]["choices"], "Azure's prompt_filter_results frame, which has no choices, is not the first chunk"
    assert "filter_results" not in r.text, "no Azure annotation reaches the caller"
    assert all(c.get("delta") is not None for e in events for c in e["choices"]), "a choice with no delta was passed on"
    usage = events[-1]["usage"]
    rows = (await azure.client.get("/v1/models/calls", params={"alias": alias}, headers=SERVICE)).json()["data"]
    row = rows["items"][0]
    assert row["outcome"] == "ok" and row["inputTokens"] > 0 and row["outputTokens"] > 0, row
    assert (row["inputTokens"], row["outputTokens"]) == (usage["prompt_tokens"], usage["completion_tokens"])


@pytest.mark.parametrize("stream", [False, True])
async def test_tool_calls_pass_through(azure: Azure, stream: bool) -> None:
    alias = await azure.alias(await azure.connect())
    r = await azure.call(alias, stream=stream, tools=True)
    assert r.status_code == 200, r.text
    sent = json.loads(azure.seen[-1].content)
    assert sent["tools"][0]["function"]["name"] == "lookup_claim", "the provider saw the offered tool"
    calls: list[dict[str, Any]]
    if stream:
        deltas: list[dict[str, Any]] = [ch["delta"] for e in _events(r) for ch in e["choices"]]
        calls = [c for d in deltas for c in cast(list[dict[str, Any]], d.get("tool_calls") or [])]
    else:
        calls = r.json()["choices"][0]["message"]["tool_calls"]
    assert [c["function"]["name"] for c in calls] == ["lookup_claim"], r.text


async def test_region_mismatch_is_recorded_and_the_call_goes_through(models: Models) -> None:
    # Warn only (owner, 2026-10-31): the call answers, and the connection and call log say where Azure answered from.
    async for azure in _azure(models, region="East US"):
        pid = await azure.connect(region="swedencentral")
        alias = await azure.alias(pid)
        plain, streamed = await azure.call(alias), await azure.call(alias, stream=True)
        assert plain.status_code == 200 and streamed.status_code == 200, plain.text
        listed = await azure.connection(pid)
        assert (listed["observedRegion"], listed["regionMismatch"]) == (
            "East US",
            "answered from East US, expected swedencentral",
        )
        rows = (await azure.client.get("/v1/models/calls", params={"alias": alias}, headers=SERVICE)).json()["data"]
        expected = "answered from East US, expected swedencentral"
        assert [(r["outcome"], r["reason"]) for r in rows["items"]] == [("ok", expected)] * 2, rows
    # Azure's display name and the region's id are the same region.
    async for azure in _azure(models, region="Sweden Central"):
        pid = await azure.connect(region="swedencentral")
        alias = await azure.alias(pid)
        assert (await azure.call(alias)).status_code == 200
        assert (await azure.connection(pid))["observedRegion"] == "Sweden Central"
        rows = (await azure.client.get("/v1/models/calls", params={"alias": alias}, headers=SERVICE)).json()["data"]
        assert [r["reason"] for r in rows["items"]] == [None]


async def test_a_connection_without_a_region_answers_and_flags_nothing(azure: Azure) -> None:
    alias = await azure.alias(await azure.connect(region=None))
    assert (await azure.call(alias)).status_code == 200
    rows = (await azure.client.get("/v1/models/calls", params={"alias": alias}, headers=SERVICE)).json()["data"]
    assert [r["reason"] for r in rows["items"]] == [None]


async def test_account_admin_manages_connections_and_others_are_refused(models: Models) -> None:
    body = {"type": "azure-openai", "baseUrl": ENDPOINT, "keyRef": "AZURE_CLAIMS", "region": "westeurope"}
    body |= {"apiVersion": "v1"}
    async for admin in _azure(models, role="admin"):
        made = await admin.client.post("/v1/models/providers", json=body | {"name": f"a-{uuid4().hex[:6]}"})
        assert made.status_code == 201, made.text
        listed = await admin.client.get("/v1/models/providers")
        assert any(r["region"] == "westeurope" and r["apiVersion"] == "v1" for r in listed.json()["data"])
    async for builder in _azure(models, role="builder"):
        refused = await builder.client.post("/v1/models/providers", json=body | {"name": f"b-{uuid4().hex[:6]}"})
        assert refused.status_code == 403, refused.text
        assert (await builder.client.get("/v1/models/providers")).status_code == 403
        # The install's own scripts still set connections up with the service token.
        assert (await builder.client.get("/v1/models/providers", headers=SERVICE)).status_code == 200
