"""The gateway client's answer to a call the gateway rejects with a status it has no reason list for: a 422
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


async def test_a_403_the_chat_draws_as_a_card_keeps_its_code_and_details() -> None:
    # Which of two accounts to use, or an app the team has off, is refused before the call leaves the gateway; told to
    # the model as a bare sentence, the chat had no card to draw and the person nothing to press.
    for code, details in (
        (
            "ACCOUNT_CHOICE_NEEDED",
            {
                "app": "GitHub",
                "appId": "plugin:opsai.github",
                "accounts": [{"connectionId": "a"}, {"connectionId": "b"}],
            },
        ),
        ("APP_OFF_FOR_TEAM", {"app": "Salesforce", "appId": "plugin:opsai.salesforce", "teamId": "team_security"}),
    ):
        RUN_CONTEXT.set(RunContext(thread="gth_1"))
        body = {
            "success": False,
            "error": {"code": code, "message": "x", "status": 403, "details": {"callId": "gwc_2", **details}},
        }
        out = await executor(403, json=body).execute("github_list_issues", {}, key="k", approval_token=None)
        assert out.ok is False and out.output["error"]["code"] == code, out.output
        assert out.output["error"]["details"]["appId"] == details["appId"], out.output
        assert out.for_model and "card above" in out.for_model, out.for_model
