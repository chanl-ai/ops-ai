"""The gateway's start-up writes to OPA survive a slow OPA (QA at cacf5bd8), by failure mode: one read past the
client's timeout while another suite loads the shared OPA fails start-up outright, and so every test that starts the
app; and an OPA that never answers holds start-up forever instead of failing within a bound."""

from __future__ import annotations

import httpx
import pytest

from ops_tools.opa import OpaClient


def _once_slow() -> tuple[OpaClient, list[str]]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        if len(seen) == 1:
            raise httpx.ReadTimeout("OPA busy", request=request)
        return httpx.Response(200, json={})

    return OpaClient(httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://opa")), seen


async def test_a_review_key_write_that_times_out_once_is_retried() -> None:
    opa, seen = _once_slow()
    await opa.load_review_key("k" * 40)
    assert seen == ["PUT", "PUT"]


async def test_a_policy_write_that_times_out_once_is_retried() -> None:
    opa, seen = _once_slow()
    await opa.load_policy("package ops.gateway")
    assert seen == ["PUT", "PUT"]


async def test_an_opa_that_never_answers_fails_start_up_within_the_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ops_tools.opa.START_UP_BOUND_S", 0.3)

    def never(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("OPA down", request=request)

    opa = OpaClient(httpx.AsyncClient(transport=httpx.MockTransport(never), base_url="http://opa"))
    with pytest.raises(httpx.ReadTimeout):
        await opa.load_review_key("k" * 40)
