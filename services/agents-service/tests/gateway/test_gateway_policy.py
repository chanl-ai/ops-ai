"""The gateway's policy in OPA, by failure mode: OPA keeping an old policy after an edit (its file watch can miss a
change on a bind mount), and another process replacing it in a shared OPA after the gateway started."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.activities.catalog import load_catalog
from ops_email import MemorySender
from ops_tools.app import create_gateway_app
from ops_tools.opa import POLICY_FILE, POLICY_ID, OpaClient, PolicyMismatchError, policy_hash
from ops_tools.registry import ToolRegistry
from ops_tools.store import CallLog
from ops_tools.tools import LocalToolRunner
from tests.gateway.conftest import OPA_URL, REVIEW_KEY, SEED, Gateway


class FakeOpa:
    """OPA's policy and data API in memory; `serve` replaces what a read of the policy returns."""

    def __init__(self) -> None:
        self.stored: str | None = None
        self.serve: str | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/policies/{POLICY_ID}":
            if request.method == "PUT":
                self.stored = request.content.decode()
                return httpx.Response(200, json={})
            raw = self.serve if self.serve is not None else self.stored
            return httpx.Response(200, json={"result": {"id": POLICY_ID, "raw": raw}}) if raw else httpx.Response(404)
        return httpx.Response(200, json={})


def app_on(opa: FakeOpa, engine: AsyncEngine) -> Any:
    return create_gateway_app(
        opa=OpaClient(httpx.AsyncClient(transport=httpx.MockTransport(opa.handle), base_url="http://opa")),
        registry=ToolRegistry(load_catalog(SEED)),
        log=CallLog(engine),
        runner=LocalToolRunner(load_catalog(SEED), MemorySender()),
        review_key=REVIEW_KEY,
    )


async def test_the_gateway_puts_its_policy_into_opa(gateway: Gateway) -> None:
    async with httpx.AsyncClient(base_url=OPA_URL) as opa:
        raw = (await opa.get(f"/v1/policies/{POLICY_ID}")).json()["result"]["raw"]
    assert policy_hash(raw) == policy_hash(POLICY_FILE.read_text())
    assert (await gateway.client.get("/health")).status_code == 200


async def test_it_refuses_to_start_when_opa_holds_another_policy(engine: AsyncEngine) -> None:
    opa = FakeOpa()
    opa.serve = "package ops.gateway\n# an older policy\n"
    app = app_on(opa, engine)
    with pytest.raises(PolicyMismatchError):
        async with app.router.lifespan_context(app):
            pass


async def test_health_reports_a_policy_replaced_after_start(engine: AsyncEngine) -> None:
    opa = FakeOpa()
    app = app_on(opa, engine)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client,
    ):
        assert (await client.get("/health")).status_code == 200
        opa.serve = "package ops.gateway\n# written by another gateway\n"
        drifted = await client.get("/health")
        assert drifted.status_code == 503 and drifted.json()["status"] == "policy_drift"
