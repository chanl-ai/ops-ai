"""The gateway client's answer to a call the gateway rejects with a status it has no reason list for (c-057): a 422
on an input the operation's schema refuses, and a body that is not JSON. Each is a failed outcome the graph or the
model reads, never an exception that ends the run."""

from __future__ import annotations

import httpx

from ops_agents.activities.gateway import RUN_CONTEXT, GatewayClient, GatewayToolExecutor, RunContext
from ops_identity import ServiceClient, dev_service_signer

ENVELOPE = {
    "success": False,
    "error": {
        "code": "invalid_input",
        "message": "input does not match get_customer's schema: customer_id (Required.)",
        "status": 422,
        "details": {"callId": "gwc_1", "reasons": ["input does not match get_customer's schema"]},
    },
}


def executor(status: int, body: bytes | None = None, json: object | None = None) -> GatewayToolExecutor:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=json, content=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer), base_url="http://gateway")
    return GatewayToolExecutor(
        GatewayClient(ServiceClient(client, dev_service_signer(), "agents", "tools", tenant=lambda: "local"))
    )


async def test_a_422_becomes_a_failed_outcome_with_the_gateways_error() -> None:
    RUN_CONTEXT.set(RunContext(thread="gth_1"))
    out = await executor(422, json=ENVELOPE).execute("get_customer", {"customerId": "x"}, key="k", approval_token=None)
    assert out.ok is False
    assert out.output["error"]["status"] == 422 and out.output["error"]["code"] == "invalid_input"
    assert "customer_id" in out.output["error"]["message"]


async def test_a_body_that_is_not_json_still_fails_with_its_status() -> None:
    RUN_CONTEXT.set(RunContext(thread="gth_1"))
    out = await executor(502, body=b"<html>bad gateway</html>").execute("x", {}, key="k", approval_token=None)
    assert out.ok is False and out.output["error"]["status"] == 502
    assert "bad gateway" in out.output["error"]["message"]
