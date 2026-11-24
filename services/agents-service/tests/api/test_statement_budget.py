"""Every GET route of agents-service in its statement budget (`budgets.toml`, data-access standard DA1 and DA6), by
failure mode: a list whose statements grow with its rows, a route over its row, and a route that opens more
transactions or checks out more connections than its row lists. The app runs on the dev caller's seeded team; the
lists `seed_team` adds rows to are named in its docstring, and a list it does not fill proves nothing about growth."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response

from ops_agents.api.agent_registry import SEED_TEAM
from ops_agents.store.api_key_copies import ApiKeyCopies, KeySummary, listed_event
from ops_agents.store.batches import Batches
from ops_agents.store.evals import EvalStore
from ops_agents.store.mailboxes import MailboxRow, MailboxStore
from ops_agents.store.tenancy import tenant_scope
from ops_agents.store.widget_deployments import WidgetDeployments
from ops_identity.fastapi import DEV_TENANT
from ops_service_kit.settings import Settings
from ops_service_kit.testing import Seeded, SeedTeam, StatementBudget, budget_check
from ops_store.database import open_database

from ..conftest import SEED, emptied, started
from ..saves import save_agent
from .test_case_record_route_pins import DISPUTE
from .test_forms import INPUTS, flow
from .test_guardrails_route_pins import RULE
from .test_skills_route_pins import SKILL
from .test_widget_registry import LIMIT_CARD

BUDGETS = Path(__file__).parents[2] / "budgets.toml"
BASIC = Path(__file__).parents[1] / "fixtures" / "engine" / "basic.yaml"
# The dev caller acting in the seeded team, as the console sends it: the team lists read that team's rows.
DEV = {"X-Team-Id": SEED_TEAM}
# `{workflow_id}` names a registry workflow and, under `definitions/`, an engine definition: one seeded id each.
REGISTRY_WORKFLOW, DEFINITION = "wire_hold_review", "refund_check"
HOLDS = {"toolIds": ["lookup_account"], "accounts": {"salesforce": "Main"}}
RUN_INPUT = {"email": {"sender": "ops@bank.example", "subject": "Hold the wire", "body": "Please hold wire 4411."}}
PATH_IDS = (
    "agent_id",
    "batch_id",
    "case_id",
    "copy",
    "deployment_id",
    "guardrail_id",
    "mailbox_id",
    "name",
    "request_id",
    "resource",
    "review_id",
    "run_id",
    "run_key",
    "skill_id",
    "slug",
    "task_id",
    "thread_id",
    "tool_id",
    "type_id",
    "version",
    "widget_id",
    "workflow_id",
)

statement_budget = pytest.fixture(budget_check)


@pytest.fixture
async def served(graph_models: Any, database_url: str) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    """The app on an engine from `open_database`, whose listeners count each request's statements, transactions and
    connection checkouts into its `http.request` line."""
    engine = open_database(database_url)
    await emptied(engine)
    settings = Settings(database_url=database_url, seed_dir=SEED)
    try:
        async with started(engine, settings, graph_models) as made:
            yield made
    finally:
        await engine.dispose()


@pytest.fixture
def app(served: tuple[FastAPI, AsyncClient]) -> FastAPI:
    return served[0]


class Caller:
    """The test's client as the budget calls it: an engine definition's path gets the definition's id, and a path in
    `swaps` (a review's, a graph run's) its own ids, which the shared `{workflow_id}`, `{thread_id}` and `{run_id}`
    templates cannot carry."""

    def __init__(self, client: AsyncClient, swaps: dict[str, str]) -> None:
        self.client = client
        self.swaps = swaps

    async def get(self, url: str, *, headers: Mapping[str, str]) -> Response:
        if url.startswith(f"/v1/workflows/definitions/{REGISTRY_WORKFLOW}"):
            url = url.replace(REGISTRY_WORKFLOW, DEFINITION, 1)
        path, mark, query = url.partition("?")
        url = self.swaps.get(path, path) + mark + query
        return await self.client.get(url, headers=headers)


@pytest.fixture
def swaps() -> dict[str, str]:
    """The paths whose ids the seed fills in: a path as the shared ids format it, to the path to call instead."""
    return {}


@pytest.fixture
def client(served: tuple[FastAPI, AsyncClient], swaps: dict[str, str]) -> Caller:
    return Caller(served[1], swaps)


def _id(answer: Any) -> str:
    assert answer.status_code in (200, 201), answer.text
    data = answer.json()["data"]
    return str(data.get("id") or data["widgetId"])


async def _channels(app: FastAPI, tag: str, agent: str) -> None:
    """A mailbox, an embed of `agent` and an API key on the dev caller's team, so the Channels list grows in each of
    its three sources."""
    db = app.state.runtime.db
    with tenant_scope(DEV_TENANT):
        await MailboxStore(db).create(
            MailboxRow(
                id=f"mbx_budget{tag.replace('-', '')}",
                team_id=SEED_TEAM,
                name=f"Mail {tag}",
                address=f"budget-{tag}@bank.example",
                provider="imap",
                created_by="b",
                created_at="n",
                updated_at="n",
            )
        )
        embed = {"id": f"wd_budget{tag.replace('-', '')}", "team_id": SEED_TEAM, "name": f"Embed {tag}"}
        made = {"agent_id": agent, "agent_version": None, "origins": ["https://budget.example"]}
        await WidgetDeployments(db).add(embed | made | {"created_by": "b", "created_at": "n", "updated_at": "n"})
        summary = {"id": f"key_budget{tag.replace('-', '')}", "name": f"Key {tag}", "prefix": f"key_budget{tag}"}
        summary |= {"teamId": SEED_TEAM, "status": "active", "target": {"kind": "agent", "id": agent}}
        summary |= {"lastUsedAt": None, "expiresAt": None, "createdAt": "2026-10-01T00:00:00.000Z"}
        await ApiKeyCopies(db).apply([listed_event(KeySummary.model_validate(summary), tenant_id=DEV_TENANT)])


async def _eval_runs(app: FastAPI, n: int, agent: str) -> None:
    """`n` kept runs of `agent`, written to the store as a run of its saved case writes them, so its runs list grows."""
    draft: dict[str, Any] = {"status": "pass", "reply": "Hello", "checks": [], "latencyMs": 3}
    row: dict[str, Any] = {"team_id": SEED_TEAM, "kind": "agent", "asset_id": agent, "version": 1, "trigger": "manual"}
    row |= {"passed": 1, "total": 1, "regressions": 0, "duration_ms": 3, "started_by": "b"}
    row["results"] = [{"caseName": "Case", "draft": draft, "live": None, "regression": False}]
    with tenant_scope(DEV_TENANT):
        for i in range(n):
            ran = {"id": f"evr_budget{n}x{i:02d}", "ran_at": f"2026-10-01T00:00:{i % 60:02d}.000Z"}
            await EvalStore(app.state.runtime.db).add_run(row | ran)


@pytest.fixture
def seed_team(served: tuple[FastAPI, AsyncClient], swaps: dict[str, str]) -> SeedTeam:
    """`n` more agents (each holding a tool, an account and a saved eval case, so the Evals suites grow), skills,
    guardrails, widgets, cases, workflows of each engine and runs of the registry workflow (each waiting at its review),
    queued engine runs, channels of each type and kept eval runs of the first agent on the dev caller's team, beside the
    seed folder's records; the path ids name the first of each, and the seeded fraud agent and its records otherwise."""
    client = served[1]
    ids: dict[str, str] = dict.fromkeys(PATH_IDS, "missing")
    ids.update(
        name="dispute_email",
        workflow_id=REGISTRY_WORKFLOW,
        version="1",
        tool_id="lookup_account",
        type_id="budget_type",
    )

    async def seed(n: int) -> Seeded:
        if n == 5:
            # One of each type under one id, which `{type_id}` names in both type routes.
            _id(await client.post("/v1/case-types", json={"id": "budget_type", "name": "Budget type"}, headers=DEV))
            body: dict[str, Any] = {"id": "budget_type", "copyOf": {"id": "write_approval"}, "name": "Budget type"}
            _id(await client.post("/v1/task-types", json=body, headers=DEV))
            body = {"graph": "complex_workflow", "metadata": {}}
            made = await client.post("/v1/threads", json=body, headers=DEV)
            assert made.status_code in (200, 201), made.text
            ids["thread_id"] = str(made.json()["data"]["threadId"])
            made = await client.post("/v1/workflows/definitions", json={"yaml": BASIC.read_text()}, headers=DEV)
            assert made.status_code == 201, made.text
            # Dev auto-approve takes the definition live, so runs of it start (and stay queued: no worker runs here).
            live = await client.post(f"/v1/workflows/definitions/{DEFINITION}/publish-requests", json={}, headers=DEV)
            assert live.status_code == 201, live.text
            ids["request_id"] = str(live.json()["data"]["id"])
            # The live-workflow route names the engine definition, which the shared `{workflow_id}` cannot carry.
            swaps[f"/v1/workflows/{REGISTRY_WORKFLOW}/live"] = f"/v1/workflows/{DEFINITION}/live"
            swaps[f"/v1/workflows/{REGISTRY_WORKFLOW}/batches"] = f"/v1/workflows/{DEFINITION}/batches"
            made = await client.post("/v1/chat/threads", json={"kbIds": []}, headers=DEV)
            assert made.status_code in (200, 201), made.text
            chat = str(made.json()["data"]["id"])
            for path in ("", "/connectors", "/settings"):
                for prefix in ("/chat", "/v1/chat"):
                    swaps[f"{prefix}/threads/{ids['thread_id']}{path}"] = f"{prefix}/threads/{chat}{path}"
            # A live workflow whose trigger has inputs, shared as a link and as a members-only page.
            made = await client.post(
                "/v1/workflows/definitions", json={"definition": flow("budget_form", INPUTS)}, headers=DEV
            )
            assert made.status_code == 201, made.text
            live = await client.post("/v1/workflows/definitions/budget_form/publish-requests", json={}, headers=DEV)
            assert live.status_code == 201, live.text
            forms: dict[str, dict[str, Any]] = {}
            for mode in ("link", "members"):
                body = {"mode": mode, "expiresInDays": 30, "dailyCap": 100, "title": f"Budget {mode}"}
                shared = await client.post("/v1/workflows/budget_form/forms", json=body, headers=DEV)
                assert shared.status_code == 201, shared.text
                forms[mode] = shared.json()["data"]
            ids.update(slug=str(forms["link"]["slug"]), form_token=str(forms["link"]["token"]))
            swaps[f"/v1/forms/{ids['slug']}/members"] = f"/v1/forms/{forms['members']['slug']}/members"
        for i in range(n):
            tag = f"{n}-{i:02d}"
            agent = _id(await client.post("/v1/agents", json={"name": f"Agent {tag}", "role": "Answers"}, headers=DEV))
            # A tool and an account on each agent, so the lists of who uses one grow with the agents.
            held = await save_agent(client, agent, HOLDS, headers=DEV)
            assert held.status_code == 200, held.text
            case_set: dict[str, Any] = {"cases": [{"name": f"Case {tag}", "input": "Hello", "checks": []}]}
            saved = await client.put(f"/v1/agents/{agent}/eval-cases", json=case_set, headers=DEV)
            assert saved.status_code == 200, saved.text
            skill = _id(await client.post("/v1/skills", json={**SKILL, "name": f"Skill {tag}"}, headers=DEV))
            rule = _id(await client.post("/v1/guardrails", json={**RULE, "name": f"Rule {tag}"}, headers=DEV))
            widget = _id(await client.post("/v1/widgets", json={**LIMIT_CARD, "name": f"Card {tag}"}, headers=DEV))
            case = _id(await client.post("/v1/cases", json={**DISPUTE, "subject": f"Dispute {tag}"}, headers=DEV))
            # A workflow of each engine, so the Workflows list grows on both sides of its union.
            _id(await client.post("/v1/workflows", json={"name": f"Flow {tag}"}, headers=DEV))
            engine_flow = {"yaml": BASIC.read_text().replace("id: refund_check", f"id: budget_flow_{n}_{i:02d}")}
            assert (await client.post("/v1/workflows/definitions", json=engine_flow, headers=DEV)).status_code == 201
            # A run of the registry workflow to its review, so its runs list and each run's journal grow.
            made = await client.post("/v1/threads", json={"graph": REGISTRY_WORKFLOW}, headers=DEV)
            assert made.status_code == 201, made.text
            waiting = str(made.json()["data"]["threadId"])
            run = await client.post(f"/v1/threads/{waiting}/runs/stream", json={"input": RUN_INPUT}, headers=DEV)
            assert run.status_code == 200 and '"interrupt"' in run.text, run.text
            graph_run = str(json.loads(run.text.split("data: ", 1)[1].split("\n", 1)[0])["runId"])
            body = {"workflowId": DEFINITION, "input": {"customerId": f"C-{tag}", "amount": 250}, "runKey": tag}
            queued = await client.post("/v1/runs", json=body, headers=DEV)
            assert queued.status_code == 202, queued.text
            await _channels(served[0], tag, agent)
            if i == 0 and n == 5:
                ids.update(agent_id=agent, skill_id=skill, guardrail_id=rule, widget_id=widget, case_id=case)
                ids.update(run_id=str(queued.json()["data"]["runId"]), review_id=waiting)
                # `_channels` names the first mailbox and embed by the tag, without its dash.
                ids.update(mailbox_id="mbx_budget500", deployment_id="wd_budget500")
                # The thread routes keep the seeded thread; a review and a graph run's events read the waiting run.
                swaps[f"/reviews/{ids['thread_id']}"] = f"/reviews/{waiting}"
                events = f"/v1/threads/{ids['thread_id']}/runs/{ids['run_id']}/events"
                swaps[events] = f"/v1/threads/{waiting}/runs/{graph_run}/events"
        # A batch of `n` rows at each size, so its page and its results file grow with the rows.
        with tenant_scope(DEV_TENANT):
            batch = await Batches(served[0].state.runtime.db).create(
                team_id=SEED_TEAM,
                workflow_id=DEFINITION,
                version=1,
                mode="live",
                file_id=f"file_budget{n}",
                file_name="refunds.csv",
                created_by="b",
                rows=[{"customerId": f"C-{n}-{i:02d}", "amount": 250} for i in range(n)],
            )
        ids["batch_id"] = batch.id
        await _eval_runs(served[0], n, ids["agent_id"])
        # `{run_id}` names a queued engine run; the eval-run read reads the first kept run instead.
        swaps[f"/v1/eval-runs/{ids['run_id']}"] = "/v1/eval-runs/evr_budget5x00"
        return Seeded(headers=DEV, ids=ids)

    return seed


async def test_every_get_stays_in_its_budget(statement_budget: StatementBudget) -> None:
    problems = await statement_budget(BUDGETS)
    assert problems == [], "\n".join(problems)
