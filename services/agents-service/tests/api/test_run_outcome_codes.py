"""What the engine reads from each gateway answer to a write (c-561), by failure mode: a write the gateway is still
running (409 write_in_progress) taken as refused, so the step leaves by its refused port while the call may still
finish; a key the gateway abandoned (call_abandoned) taken as refused instead of known unsent; a pass whose run has a
newer owner (lease_superseded) carrying on; and a claim the gateway lost read as an ordinary failure."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from ops_agents.activities.gateway import GatewayClient
from ops_agents.api.engine_host import GatewayTools
from ops_checkpointer import LeaseSupersededError
from ops_identity import ServiceClient, dev_service_signer

KEY = "wfrun_abc:hold:1:1"


def tools(handler: Any) -> GatewayTools:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://tools")
    return GatewayTools(
        GatewayClient(ServiceClient(client, dev_service_signer(), "agents", "tools", tenant=lambda: "local"))
    )


def refusing(code: str) -> Any:
    def handler(req: httpx.Request) -> httpx.Response:
        err = {"code": code, "message": code.replace("_", " "), "details": {"callId": "gwc_1", "reasons": [code]}}
        return httpx.Response(409, json={"success": False, "error": err})

    return handler


async def test_a_write_still_running_at_the_gateway_is_pending_not_refused() -> None:
    result = await tools(refusing("write_in_progress")).call("place_hold", {}, KEY, 1, None)
    assert (result.ok, result.pending, result.refused) == (False, True, False)


async def test_an_abandoned_key_is_known_unsent_not_refused() -> None:
    result = await tools(refusing("call_abandoned")).call("place_hold", {}, KEY, 1, None)
    assert (result.ok, result.not_sent, result.refused) == (False, True, False)


async def test_a_superseded_lease_stops_the_pass() -> None:
    with pytest.raises(LeaseSupersededError):
        await tools(refusing("lease_superseded")).call("place_hold", {}, KEY, 1, None)


async def test_a_claim_the_gateway_lost_reads_as_lost() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        call = {"id": "gwc_1", "outcome": "lost", "effect": True, "error": None}
        assert json.loads(req.content)["key"] == KEY
        return httpx.Response(200, json={"success": True, "data": {"abandoned": False, "call": call}})

    found = await tools(handler).find(KEY, "place_hold")
    assert found is not None and (found.ok, found.lost) == (False, True)
