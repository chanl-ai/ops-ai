"""The egress client keeps no cookies (c-038): one client serves every tenant, workflow and caller, so a cookie an
upstream sets on one call must never ride on another. One test per way a cookie could leak or be lost."""

from __future__ import annotations

from typing import Any

import httpx

from ops_tools.egress import EgressPolicy, egress_client
from ops_tools.executor import HttpExecutor

HOST = "api.example.test"
OP: dict[str, Any] = {"name": "get_thing", "method": "GET", "path": "/thing", "headers": [], "masked_output": []}


class _AllowAll:
    async def host_allowed(self, tenant_id: str, host: str) -> bool:
        return True

    async def ranges(self, tenant_id: str) -> list[str]:
        return []


def _module(tenant: str) -> dict[str, Any]:
    return {"endpoint": f"https://{HOST}", "egress_hosts": [HOST], "tenant_id": tenant, "timeout_ms": 8000}


def _setup() -> tuple[HttpExecutor, list[str | None]]:
    """An executor on the real egress client whose upstream sets a session cookie on every answer and records the
    Cookie header each request carried."""
    sent: list[str | None] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        sent.append(request.headers.get("cookie"))
        return httpx.Response(200, json={"ok": True}, headers={"set-cookie": "session=tenant-secret; Path=/"})

    policy = EgressPolicy(_AllowAll())  # pyright: ignore[reportArgumentType]
    client = egress_client(policy, transport=httpx.MockTransport(upstream))
    return HttpExecutor(client, policy), sent


async def test_a_cookie_one_tenants_upstream_sets_never_reaches_another_tenants_call() -> None:
    executor, sent = _setup()
    assert (await executor.run(_module("tenant_a"), OP, {})).ok
    assert (await executor.run(_module("tenant_b"), OP, {})).ok
    assert sent == [None, None], "tenant B's call carried tenant A's session"


async def test_a_cookie_is_not_replayed_within_one_tenant_either() -> None:
    executor, sent = _setup()
    for _ in range(2):
        assert (await executor.run(_module("tenant_a"), OP, {})).ok
    assert sent == [None, None], "a second call carried the first call's session"


async def test_a_cookie_header_set_on_the_operation_is_still_sent() -> None:
    executor, sent = _setup()
    op = {**OP, "headers": [{"key": "Cookie", "value": "region=ca"}]}
    for _ in range(2):
        assert (await executor.run(_module("tenant_a"), op, {})).ok
    assert sent == ["region=ca", "region=ca"], "only the operation's own cookie goes out, every time"
