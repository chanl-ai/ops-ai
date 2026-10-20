"""The floor for extracted fields read from platform-service's `extractionFloor` policy (c-157), by failure mode: the
worker reads another tenant's floor; a read that fails lowers the floor to the default; a value that is not a
confidence is used; a cleared policy has no floor at all. platform-service is faked at its documented route."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

from ops_extract.floor import FloorUnreadError, PlatformFloor
from ops_identity import ServiceClient, dev_service_signer


def floor_of(answer: httpx.Response, seen: list[httpx.Request] | None = None) -> PlatformFloor:
    def handle(request: httpx.Request) -> httpx.Response:
        (seen if seen is not None else []).append(request)
        return answer

    http = httpx.AsyncClient(base_url="http://platform", transport=httpx.MockTransport(handle))
    return PlatformFloor(ServiceClient(http, dev_service_signer(), "agents", "platform", tenant=lambda: "acme"))


def policy(value: Any) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "data": {"key": "extractionFloor", "value": value}})


async def test_the_floor_is_the_policy_read_with_the_tenants_token() -> None:
    seen: list[httpx.Request] = []
    assert await floor_of(policy(0.95), seen).extraction_floor() == 0.95
    [r] = seen
    token = r.headers["authorization"].removeprefix("Bearer ")
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    assert r.url.path == "/v1/policies/extractionFloor" and claims["tenant_id"] == "acme"


async def test_a_cleared_policy_is_the_default_floor() -> None:
    assert await floor_of(policy(None)).extraction_floor() == 0.8


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(503, json={}), httpx.Response(200, text="not json"), policy(True), policy(1.5), policy("0.9")],
)
async def test_an_unread_or_wrong_floor_stops_the_step_instead_of_using_the_default(answer: httpx.Response) -> None:
    with pytest.raises(FloorUnreadError):
        await floor_of(answer).extraction_floor()
