"""A failed call says which side it broke on (c-038): one test per way the side or the phase could be reported wrong,
through the real HttpExecutor against a transport that fails the way the network would."""

from __future__ import annotations

import socket
import ssl
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from ops_tools.egress import EgressPolicy, egress_client
from ops_tools.executor import HttpExecutor

from .test_calls import MODULE as BANK
from .test_calls import Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]

HOST = "api.example.test"
# An address a connect error's own text carries; it must never reach the message or the log.
DIALLED = "203.0.113.9"
MODULE: dict[str, Any] = {
    "endpoint": f"https://{HOST}",
    "egress_hosts": [HOST],
    "tenant_id": "local",
    "timeout_ms": 8000,
}
OP: dict[str, Any] = {"name": "get_thing", "method": "GET", "path": "/thing", "headers": [], "masked_output": []}


class Allow:
    async def check_url(self, tenant_id: str, url: str) -> str:
        return HOST


def _tls_error(request: httpx.Request) -> httpx.ConnectError:
    error = httpx.ConnectError(f"handshake with {DIALLED} failed", request=request)
    error.__cause__ = ssl.SSLCertVerificationError(1, "certificate verify failed: unable to get local issuer")
    return error


Failure = Callable[[httpx.Request], httpx.HTTPError]


def _connect_timeout(r: httpx.Request) -> httpx.HTTPError:
    return httpx.ConnectTimeout(f"connect to {DIALLED} timed out", request=r)


def _pool_timeout(r: httpx.Request) -> httpx.HTTPError:
    return httpx.PoolTimeout("no connection in the pool", request=r)


def _refused(r: httpx.Request) -> httpx.HTTPError:
    return httpx.ConnectError(f"[Errno 61] Connect call failed ('{DIALLED}', 443)", request=r)


def _read_timeout(r: httpx.Request) -> httpx.HTTPError:
    return httpx.ReadTimeout("no answer", request=r)


def _dropped(r: httpx.Request) -> httpx.HTTPError:
    return httpx.RemoteProtocolError("server disconnected", request=r)


FAILURES: list[tuple[Failure, str, str]] = [
    (_connect_timeout, "CONNECT_TIMEOUT", "ours"),
    (_pool_timeout, "POOL_TIMEOUT", "ours"),
    (_refused, "CONNECT_FAILED", "ours"),
    (_tls_error, "TLS_FAILED", "ours"),
    (_read_timeout, "UPSTREAM_TIMEOUT", "upstream"),
    (_dropped, "UPSTREAM_ERROR", "upstream"),
]


@pytest.mark.parametrize(("failure", "code", "side"), FAILURES)
async def test_a_transport_failure_names_its_phase_and_side_and_no_address(
    failure: Failure, code: str, side: str
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise failure(request)

    executor = HttpExecutor(httpx.AsyncClient(transport=httpx.MockTransport(fail)), Allow())  # pyright: ignore[reportArgumentType]
    outcome = await executor.run(MODULE, OP, {})
    error = outcome.output["error"]
    assert (outcome.ok, error["code"], error["side"]) == (False, code, side)
    assert HOST in error["message"] and DIALLED not in error["message"]


@pytest.mark.parametrize(
    ("status", "code"), [(503, "UPSTREAM_ERROR"), (429, "RATE_LIMITED"), (422, "INVALID_ARGUMENTS")]
)
async def test_an_upstream_answer_is_the_upstreams_failure_with_its_status(status: int, code: str) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status)))
    outcome = await HttpExecutor(client, Allow()).run(MODULE, OP, {})  # pyright: ignore[reportArgumentType]
    assert outcome.output["error"] == {
        "code": code,
        "message": outcome.output["error"]["message"],
        "status": status,
        "side": "upstream",
    }


async def test_the_executions_log_shows_the_side_a_call_broke_on(gateway: Gateway) -> None:  # noqa: F811
    # The fake bank's /slow answers only to a caller willing to wait 5 s: connected, then no answer in time.
    base = f"/v1/tool-modules/{BANK}"
    detail = (await gateway.client.get(base)).json()["data"]
    op_id = next(o["id"] for o in detail["operations"] if o["name"] == gateway.tool("limited"))
    edited = await gateway.client.patch(f"{base}/operations/{op_id}", json={"path": "/slow", "timeoutMs": 1_000})
    assert edited.status_code == 200, edited.text
    requested = await gateway.client.post(f"{base}/versions", json={"note": "c-038"})
    assert requested.status_code == 200
    # A new path is a major change: it runs only once Security approves the version.
    review = next(x["id"] for x in requested.json()["data"]["reviews"] if x["decision"] == "pending")
    decided = await gateway.client.post(
        f"{base}/reviews/{review}/decide", json={"decision": "approved"}, headers={"X-Dev-User": "Nadia Petrov"}
    )
    assert decided.status_code == 200, decided.text
    r = await gateway.call("limited", {}, step="s1")
    out = r.json()["data"]["output"]
    assert (out["error"]["code"], out["error"]["side"]) == ("UPSTREAM_TIMEOUT", "upstream")
    rows = (await gateway.client.get("/v1/executions", params={"tool": gateway.tool("limited")})).json()["data"]["data"]
    assert (rows[0]["status"], rows[0]["errorCode"], rows[0]["failureSide"]) == (
        "error",
        "UPSTREAM_TIMEOUT",
        "upstream",
    )
    assert "1000 ms" in rows[0]["errorMessage"]


class _Unresolvable:
    async def resolve(self, host: str, port: int) -> list[str]:
        raise socket.gaierror(8, "nodename nor servname provided, or not known")


class _AllowAll:
    async def host_allowed(self, tenant_id: str, host: str) -> bool:
        return True

    async def ranges(self, tenant_id: str) -> list[str]:
        return []


async def test_a_host_that_does_not_resolve_is_a_connect_failure_not_a_crash() -> None:
    # Through the real egress client: the resolver's error must leave as a connect failure on our side.
    policy = EgressPolicy(_AllowAll(), _Unresolvable())  # pyright: ignore[reportArgumentType]
    outcome = await HttpExecutor(egress_client(policy), policy).run({**MODULE, "tenant_id": "local"}, OP, {})
    error = outcome.output["error"]
    assert (error["code"], error["side"]) == ("CONNECT_FAILED", "ours")
