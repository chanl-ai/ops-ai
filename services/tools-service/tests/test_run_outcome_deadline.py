"""How long the gateway may take over an operation (c-561), by failure mode: the engine's step deadline falls short of
the operation's own time limit, so a write the gateway is still running is failed as uncertain while it may finish."""

from __future__ import annotations

from .conftest import service_headers
from .test_calls import Gateway, gateway

__all__ = ["gateway"]  # the fixture, used by name


async def test_the_tool_lookup_says_how_long_the_gateway_may_take(gateway: Gateway) -> None:
    r = await gateway.client.get(f"/v1/tools/{gateway.tool('place_hold')}", headers=service_headers(gateway.tenant))
    assert r.status_code == 200, r.text
    # The bank module's own limit, 8 s, and the gateway's margin for signing in and the egress check.
    assert r.json()["data"]["deadlineSeconds"] == 13.0, r.json()
