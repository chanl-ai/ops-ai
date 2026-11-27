"""How many transactions the gateway's routes hold, by failure mode: a route opening one transaction per store call, so
a fence is raised or a key abandoned apart from the read that checked it, or the grantable list reads its modules and
their test accounts at different moments; and a connection held while platform-service says which writes wait. A call
(`/v1/calls`, `/v1/code-runs/calls`) runs the tool, so it holds none (`app.py`)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.pool import QueuePool

from ops_identity import dev_service_signer, mint_service_token
from ops_service_kit.logging import captured_logging
from ops_service_kit.settings import Settings
from ops_store.database import open_database
from ops_tools.modules.policy import WriteApprovals
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, opa_client
from .service_clients import fake_service


class Gateway:
    def __init__(self, client: httpx.AsyncClient, tenant: str, held: list[int]) -> None:
        self.client, self.tenant, self.held = client, tenant, held
        token = mint_service_token(
            dev_service_signer(),
            service="agents",
            audience="tools",
            tenant_id=tenant,
            scopes=["tools:view"],
            team_id="team_ops",
        )
        self.headers = {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def gateway(seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]) -> AsyncIterator[Gateway]:
    """The gateway on an engine whose transactions the request line counts, with platform-service's write approval
    policy answering from memory and noting how many connections were out when it was asked."""
    engine = open_database(Settings().database_url)
    pool = engine.pool
    assert isinstance(pool, QueuePool)
    held: list[int] = []

    def platform(request: httpx.Request) -> httpx.Response:
        held.append(pool.checkedout())
        return httpx.Response(
            200, json={"success": True, "data": {"key": "appChanges", "value": {"*": {"makersAsk": True}}}}
        )

    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    async with opa_client() as opa:
        approvals = WriteApprovals(fake_service(platform, "platform", ["settings:view"]))
        app = build_app(engine, seed, tenant, opa=opa, write_approvals=approvals)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c:
            yield Gateway(c, tenant, held)
    await engine.dispose()


async def test_gateway_reads_and_local_writes_each_hold_one_transaction_and_none_while_platform_answers(
    gateway: Gateway,
) -> None:
    listed = await gateway.client.get("/v1/grantable-operations", headers=gateway.headers)
    tool = listed.json()["data"][0]["name"]
    steps: list[tuple[str, str, str, Any, int]] = [
        ("grantable", "GET", "/v1/grantable-operations", None, 200),
        ("tool", "GET", f"/v1/tools/{tool}", None, 200),
        ("tool missing", "GET", "/v1/tools/no_such_tool", None, 404),
        ("fence", "POST", "/v1/fences", {"thread": "thr_tx", "generation": 2}, 200),
        ("fence below", "POST", "/v1/fences", {"thread": "thr_tx", "generation": 1}, 409),
        ("abandon", "POST", "/v1/calls/abandon", {"key": "k-tx", "tool": "lookup_case"}, 200),
        ("abandon again", "POST", "/v1/calls/abandon", {"key": "k-tx", "tool": "lookup_case"}, 200),
    ]
    counts: dict[str, int] = {}
    for name, method, path, body, status in steps:
        with captured_logging("tools-gateway-tx") as stream:
            r = await gateway.client.request(method, path, json=body, headers=gateway.headers)
        assert r.status_code == status, (name, r.text)
        line = next(json.loads(x) for x in stream.getvalue().splitlines() if '"http.request"' in x)
        counts[name] = int(line["db.tx_count"])
    assert counts == {name: 1 for name, *_ in steps}, counts
    # platform-service is asked three times per list (the team's levels, each app's, then the Security team's floor).
    assert gateway.held == [0, 0, 0] * 2, gateway.held
