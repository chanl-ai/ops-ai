"""Workflows come from agents-service (c-039), one test per way an approval could govern the wrong thing: a fixture
workflow accepted or a real one refused, a workflow whose team nobody here knows handed to the all-scope team, a
stopped agents-service answered from stale or invented data, one tenant's workflows answering another, fixture cases
offered in the test panel, and a running service reading tests/."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import dev_service_signer
from ops_policy import verify
from ops_service_kit.settings import Settings
from ops_tools.modules.seed import load
from ops_tools.modules.workflows import AgentsWorkflows
from ops_tools.store.modules import ModuleStore

from .conftest import Api, build_app
from .service_clients import fake_service

REAL = {
    "id": "dispute_email",
    "name": "Dispute email",
    "owner": "Card Services",
    "teamId": "team_cards",
    "status": "live",
}
NOBODYS = {"id": "orphan_flow", "name": "Orphan flow", "owner": "Nobody", "teamId": "team_unknown", "status": "live"}


class FakeAgents:
    """agents-service's internal workflow route: records who asked, and can be stopped."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows, self.down = rows, False
        self.asked: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            return httpx.Response(503)
        token = request.headers["Authorization"].removeprefix("Bearer ")
        claims = verify(token, dev_service_signer().verifier("agents"))
        self.asked.append(str(claims["tenant_id"]))
        return httpx.Response(200, json={"success": True, "data": self.rows})


def directory(agents: FakeAgents, clock: Any = None) -> AgentsWorkflows:
    return AgentsWorkflows(fake_service(agents.handler, "agents"), **({"clock": clock} if clock else {}))


@pytest.fixture
async def agents() -> FakeAgents:
    return FakeAgents([REAL, NOBODYS])


@pytest.fixture
async def api(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], agents: FakeAgents
) -> AsyncIterator[Api]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    app = build_app(engine, seed, tenant, workflows=directory(agents))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c:
        yield Api(c, tenant)


def request(workflow: str) -> dict[str, Any]:
    return {
        "workflowId": workflow,
        "environment": "production",
        "operations": ["get_customer_profile"],
        "expiresInDays": 90,
        "justification": "Disputes need the customer's profile",
    }


async def test_an_approval_for_a_real_workflow_is_requested_and_waits_for_its_run(api: Api) -> None:
    made = await api.call("POST", "/mod_core_banking/approvals", json=request("dispute_email"))
    assert made.status_code == 201, made.text
    approval = made.json()["data"]
    assert approval["workflowName"] == "Dispute email"
    # Decided by its system workflow run (c-257; test_apply_tool_access), which the run key names.
    assert (approval["status"], approval["reviewId"]) == ("requested", f"tool_access.requested:{approval['id']}")


async def test_a_workflow_agents_service_does_not_have_is_refused(api: Api) -> None:
    r = await api.call("POST", "/mod_core_banking/approvals", json=request("wf_wire"))
    assert r.status_code == 400 and "Choose a workflow" in r.json()["error"]["message"], r.text


async def test_a_workflow_of_a_team_the_seed_does_not_hold_is_granted_for_that_team(
    api: Api, engine: AsyncEngine, tenant: str
) -> None:
    # A team made on the Teams page is a platform team the dev seed does not list (c-423): the grant names it.
    r = await api.call("POST", "/mod_core_banking/approvals", json=request("orphan_flow"))
    assert r.status_code == 201, r.text
    stored = await ModuleStore(engine).get_any(tenant, "mod_core_banking")
    assert stored is not None
    made = next(a for a in stored["approvals"] if a["id"] == r.json()["data"]["id"])
    assert made["workflow_team_id"] == "team_unknown", made


async def test_a_stopped_agents_service_is_503_never_a_guess(api: Api, agents: FakeAgents) -> None:
    agents.down = True
    r = await api.call("POST", "/mod_core_banking/approvals", json=request("dispute_email"))
    assert r.status_code == 503 and r.json()["error"]["code"] == "workflows_unavailable", r.text


async def test_each_tenant_asks_for_its_own_workflows_and_is_cached_briefly(agents: FakeAgents) -> None:
    now = [0.0]
    workflows = directory(agents, clock=lambda: now[0])
    await workflows.all("ten_a")
    await workflows.all("ten_a")
    await workflows.all("ten_b")
    assert agents.asked == ["ten_a", "ten_b"], "a second tenant never reads the first one's answer"
    now[0] = 31.0
    await workflows.all("ten_a")
    assert agents.asked == ["ten_a", "ten_b", "ten_a"], "the cache lasts 30 seconds"


async def test_the_test_panel_runs_as_an_approval_workflow_with_typed_sample_values(api: Api) -> None:
    detail = (await api.call("GET", "/mod_core_banking")).json()["data"]
    owner, *contexts = detail["runContexts"]
    assert owner["id"] == "owner", "the owner's try comes first, so the panel's default needs no approval"
    assert contexts and all(c["caseId"] == "sample" and c["bindings"] == {} for c in contexts), contexts
    assert {c["id"] for c in contexts} == {c["workflowId"] for c in contexts}, "one context per workflow, no case"


def test_no_settings_default_points_into_tests() -> None:
    seed = Settings().tools_seed_file
    assert "tests" not in seed.parts and seed.is_file(), seed
    loaded = json.loads(seed.read_text())
    assert "workflows" not in loaded and "runContexts" not in loaded, "workflows are agents-service's"
