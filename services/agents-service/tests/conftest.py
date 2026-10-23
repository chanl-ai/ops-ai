"""Shared test wiring: a scripted model standing in for the provider, and the app on an in-memory database."""

from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.activities.catalog import load_catalog
from ops_agents.api.app import create_app
from ops_agents.graphs.models import Facts, Grade
from ops_agents.store.base import metadata
from ops_agents.store.tenancy import LOCAL_TENANT, tenant_scope
from ops_engine.store import metadata as engine_metadata
from ops_service_kit.settings import Settings
from ops_service_kit.testdb import isolate_from_stack, refusal
from tests.knowledge_fixture import FixtureKnowledge

from .contract import response_checker

SEED = Path(__file__).parent / "fixtures" / "seed"
ROOT = Path(__file__).parents[1]
# The running stack's, exported by `make` from the root .env. Cleared in pytest_configure, before test modules are
# collected: they build Settings at their own import (before any fixture runs) and would otherwise call the live
# models-service. Not at this module's import: scripts/scripted_server.py imports it for the scripted model, and a use
# case stack's agents must keep the models-service route its harness sets.
STACK_ENV = ("OPS_EGRESS_RESOLVE", "OPS_MODELS_URL", "OPS_MODELS_KEY")
_WIRE = re.compile(r"\bW-\d+\b")
_START_WORKFLOW = re.compile(r"Start workflow (\w+):(.*)", re.S)
_CALL = re.compile(r"\bcall (\w+) (\{.*\})", re.S)
# Memory extraction (c-124): "My <key> is <value>" is a fact, "I prefer <value>" a preference, "maybe my <key> is
# <value>" a guess below the confidence floor. The scripted model answers the extractor's schema with them.
_FACT = re.compile(r"(maybe )?my ([a-z ]{2,40}?) is ([^.,;]+)", re.I)
_PREFER = re.compile(r"\bI prefer ([^.,;]+)", re.I)


def remembered(text: str) -> dict[str, Any]:
    found: list[dict[str, Any]] = [
        {
            "kind": "fact",
            "key": m.group(2).strip(),
            "value": m.group(3).strip(),
            "confidence": 0.3 if m.group(1) else 0.9,
        }
        for m in _FACT.finditer(text)
    ]
    found += [
        {"kind": "preference", "key": "prefers", "value": m.group(1).strip(), "confidence": 0.9}
        for m in _PREFER.finditer(text)
    ]
    return {"memories": found}


# A widget button's reply (c-082): "<text> (action: <tool>, key: value, ...)" asks for one granted tool.
_ACTION = re.compile(r"\(action: (\w+)((?:, [^:,()]+: [^,()]+)*)\)")
_CHILD = re.compile(r"gth_\w+")
_IMAGE = re.compile(r"\bshow image (\S+)")


def pytest_configure(config: pytest.Config) -> None:
    isolate_from_stack()
    for name in STACK_ENV:
        os.environ.pop(name, None)
    # Before any fixture or migration: the test database only, never the live one (ops_service_kit.testdb).
    if (why := refusal(Settings().database_url, os.environ.get("OPS_TEST_DATABASE_URL"))) is not None:
        pytest.exit(why, returncode=4)


def _last_user_text(messages: list[ModelMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, ModelRequest):
            for p in m.parts:
                if isinstance(p, UserPromptPart) and isinstance(p.content, str):
                    return p.content
    return ""


def structured(info: AgentInfo, args: dict[str, Any]) -> ModelResponse:
    """A structured answer in the form the request asks for: the JSON a native response format wants (the kernel's
    schema turns), else a call of the output tool (the guardrail check's classifier)."""
    if info.model_request_parameters.output_mode == "native":
        return ModelResponse(parts=[TextPart(json.dumps(args))])
    return ModelResponse(parts=[ToolCallPart("final_result", args)])


def scripted(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """Replies by keyword so each test can drive one path: tool results first, then citations, then tool calls."""
    last = messages[-1]
    returns = (
        [p for p in last.parts if isinstance(p, ToolReturnPart | RetryPromptPart)]
        if isinstance(last, ModelRequest)
        else []
    )
    if returns:
        body = " ".join(str(p.content) for p in returns)
        if "rejected" in body:
            return ModelResponse(parts=[TextPart("Understood. The hold was rejected, so the wire continues.")])
        if "waiting_review" in body:
            child = _CHILD.search(body)
            return ModelResponse(
                parts=[TextPart(f"The workflow is waiting for a review: {child.group(0) if child else ''}.")]
            )
        if "'finished'" in body:
            return ModelResponse(parts=[TextPart("The workflow finished.")])
        if "reference" in body:
            return ModelResponse(parts=[TextPart("The hold is in place.")])
        return ModelResponse(parts=[TextPart("Here is what I found.")])
    text = _last_user_text(messages)
    tools = {t.name for t in info.function_tools}
    if text.startswith("<remember>") and info.model_request_parameters.output_mode in ("native", "tool"):
        return structured(info, remembered(text))
    if "<knowledge>" in text and "limit" in text.lower():
        return ModelResponse(parts=[TextPart("The daily wire limit for a personal account is $25,000 online [1].")])
    if (wire := _WIRE.search(text)) and "place_wire_hold" in tools:
        args = {"wireId": wire.group(0), "hours": 24, "reason": "First wire to a payee added this morning."}
        return ModelResponse(parts=[ToolCallPart("place_wire_hold", args)])
    if (start := _START_WORKFLOW.search(text)) and f"workflow__{start.group(1)}" in tools:
        args = {"sender": "maria.lopez@example.com", "subject": "Disputed charge", "body": start.group(2).strip()}
        return ModelResponse(parts=[ToolCallPart(f"workflow__{start.group(1)}", args)])
    if (action := _ACTION.search(text)) and action.group(1) in tools:
        pairs = [p.split(": ", 1) for p in action.group(2).split(", ") if ": " in p]
        return ModelResponse(parts=[ToolCallPart(action.group(1), {k.strip(): v.strip() for k, v in pairs})])
    # The chat home's first start (c-469): the team's default agent lists the person's Human Tasks.
    if "what needs me" in text.lower() and "my_human_tasks" in tools:
        return ModelResponse(parts=[ToolCallPart("my_human_tasks", {"which": "mine"})])
    # "call <tool> <json>" calls any tool the turn was granted with those arguments: how a use case drives a registry
    # operation by name without a provider.
    if (call := _CALL.search(text)) and call.group(1) in tools:
        return ModelResponse(parts=[ToolCallPart(call.group(1), json.loads(call.group(2)))])
    # A reply carrying a remote image, as text the model read could: the console must not load it (c-055 uc-074).
    if image := _IMAGE.search(text):
        return ModelResponse(parts=[TextPart(f"Here is the chart. ![balance chart]({image.group(1)})")])
    if "CHQ-" in text and "lookup_account" in tools:
        return ModelResponse(parts=[ToolCallPart("lookup_account", {"query": "CHQ-2219"})])
    if "<knowledge>" in text:
        # Any other turn with passages answers from the first one and cites it, as a model told to cite would.
        return ModelResponse(parts=[TextPart("Here is what the policy says [1].")])
    return ModelResponse(parts=[TextPart("I could not find that.")])


async def scripted_stream(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
    response = scripted(messages, info)
    for i, part in enumerate(response.parts):
        if isinstance(part, TextPart):
            for k in range(0, len(part.content), 7):
                yield part.content[k : k + 7]
        elif isinstance(part, ToolCallPart):
            yield {
                i: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args), tool_call_id=part.tool_call_id)
            }


def scripted_model() -> FunctionModel:
    return FunctionModel(scripted, stream_function=scripted_stream)


LOOP_ROWS = [{"limit": "ATM withdrawal, per day", "amount": "1,000"}]


def looping_model(*, text: str = "") -> FunctionModel:
    """A model that never finishes: every step writes `text` (when given) and calls the built-in present tool, which
    no tool budget charges, so only the agent's step limit can stop the turn."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        parts: list[Any] = [TextPart(text)] if text else []
        return ModelResponse(parts=[*parts, ToolCallPart("present", {"shape": "rows", "data": LOOP_ROWS})])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if text:
            yield text
        yield {1: DeltaToolCall(name="present", json_args=json.dumps({"shape": "rows", "data": LOOP_ROWS}))}

    return FunctionModel(respond, stream_function=stream)


class FakeGraphModels:
    """Workflow model calls without a provider. `scores` are returned by grade in order, then the last repeats."""

    def __init__(self, scores: list[float] | None = None) -> None:
        self.scores = scores or [0.9]
        self.graded = 0
        self.extracted: list[str] = []

    async def classify(self, text: str, labels: list[str]) -> str:
        return labels[0]

    async def extract(self, category: str, name: str, text: str) -> Facts:
        self.extracted.append(name)
        return Facts(summary=text[:60])

    async def draft(self, email: str, evidence: str, feedback: str | None) -> str:
        return f"Draft replying to the dispute. Evidence: {evidence[:40]}"

    async def grade(self, email: str, draft: str) -> Grade:
        score = self.scores[min(self.graded, len(self.scores) - 1)]
        self.graded += 1
        return Grade(score=score, feedback="Fine.")

    async def extract_records(self, schema: str, text: str) -> list[dict[str, Any]]:
        """Persons from the fixture levy notice's text layer (scripts/make_mailbox_fixture.py): one record per
        `Debtor n:` block. Whitespace-tolerant, since a PDF parser may join a page's lines."""
        block = re.compile(
            r"Debtor \d+:\s*(?P<name>.+?)\s+Address:\s*(?P<address>.+?)\s+SSN \(last four\):\s*(?:\*+-\*+-)?"
            r"(?P<ssn_last4>\d{4})\s+Amount:\s*(?P<amount>\S+)\s+Court:\s*(?P<court>.+?)\s+Case No:\s*(?P<case_no>\S+)",
            re.DOTALL,
        )
        return [m.groupdict() for m in block.finditer(text)]


@pytest.fixture(autouse=True)
def _no_dev_stack_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`make` exports the root .env, which points at the running stack: OPS_EGRESS_RESOLVE maps a fake bank's name (and
    Settings refuses it outside dev), and OPS_MODELS_URL reaches the live models-service, whose aliases replace the
    fixture's. Tests build their own and never read the stack's."""
    for name in STACK_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def database_url() -> str:
    """The PostgreSQL test database, migrated to head once per session."""
    url = Settings().database_url
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    return url


@pytest.fixture
def local_tenant() -> Iterator[None]:
    """For a test that calls a store directly: the tenant a request or a loop would otherwise set."""
    with tenant_scope(LOCAL_TENANT):
        yield


@pytest.fixture
def graph_models() -> FakeGraphModels:
    return FakeGraphModels()


@pytest.fixture
async def client(graph_models: FakeGraphModels) -> AsyncIterator[AsyncClient]:
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=graph_models,
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            event_hooks={"response": [response_checker(app)]},
        ) as c,
    ):
        yield c


def fixture_knowledge() -> FixtureKnowledge:
    """The fixture catalogue's passages and knowledge bases, standing in for kb-service."""
    return FixtureKnowledge(load_catalog(SEED))


def sse_events(raw: str) -> list[dict[str, Any]]:
    """Parses the stream the way apps/console/src/lib/api/chat-http.ts does: split on a blank line, read data lines."""
    out: list[dict[str, Any]] = []
    for frame in raw.split("\n\n"):
        data = "".join(line[5:].strip() for line in frame.split("\n") if line.startswith("data:"))
        if data:
            out.append(json.loads(data))
    return out


async def step_up(client: AsyncClient, user: str | None = None) -> str:
    """A real step-up token for the caller (or `user` via X-Dev-User), as the console's "Confirm it is you" gets one."""
    headers = {"X-Dev-User": user} if user else {}
    res = await client.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["data"]["token"]


async def decide(
    client: AsyncClient, tid: str, decision: str = "approved", *, reason: str | None = None, user: str | None = None
) -> dict[str, Any]:
    """Decides a paused review the only way a review can be decided, POST /reviews/{id}/decision; returns the review."""
    body: dict[str, Any] = {"decision": decision} | ({"reason": reason} if reason else {})
    res = await client.post(f"/reviews/{tid}/decision", json=body, headers={"X-Dev-User": user} if user else {})
    assert res.status_code == 200, res.text
    return res.json()["data"]


async def last_run(client: AsyncClient, tid: str) -> dict[str, Any]:
    """The thread's latest run from its journal: status (done, interrupted, error) and the nodes it ran."""
    return (await client.get(f"/v1/threads/{tid}/runs")).json()["data"][-1]
