"""Running one tool from its page (`POST /v1/tool-modules/{id}/operations/{op}/run`), by failure mode: a
Mock run reaches the system; a Real run skips the gateway (no call row, no checks); and the route answers for a tool
the module does not have."""

from __future__ import annotations

from .test_calls import MODULE, Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]

TEAM = {"X-Team-Id": "team_platform"}


def url(g: Gateway, base: str) -> str:
    return f"/v1/tool-modules/{MODULE}/operations/{g.tool(base)}/run"


async def test_a_mock_run_reaches_nothing(gateway: Gateway) -> None:  # noqa: F811
    r = await gateway.client.post(
        url(gateway, "get_account"), json={"mode": "mock", "input": {"accountId": "A"}}, headers=TEAM
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["mocked"] is True
    assert not gateway.received


async def test_a_real_run_is_a_logged_gateway_call(gateway: Gateway) -> None:  # noqa: F811
    r = await gateway.client.post(
        url(gateway, "get_account"), json={"mode": "real", "input": {"accountId": "A"}}, headers=TEAM
    )
    assert r.status_code == 200, r.text
    out = r.json()["data"]
    assert (out["decision"], out["mocked"]) == ("allow", False), out
    assert [x["path"] for x in gateway.received] == ["/v1/accounts/A"]
    rows = (await gateway.client.get("/v1/executions", params={"tool": gateway.tool("get_account")})).json()["data"][
        "data"
    ]
    assert [row["id"] for row in rows] == [out["callId"]]


async def test_a_tool_the_module_does_not_have_is_not_found(gateway: Gateway) -> None:  # noqa: F811
    r = await gateway.client.post(url(gateway, "no_such_tool"), json={"mode": "mock", "input": {}}, headers=TEAM)
    assert r.status_code in (404, 400), r.text


async def test_a_real_run_acts_for_the_person_who_pressed_run(gateway: Gateway) -> None:  # noqa: F811
    # Their own sign-in signs it where each person signs in, and Usage names them when no team account signed it.
    r = await gateway.client.post(
        url(gateway, "get_account"), json={"mode": "real", "input": {"accountId": "P"}}, headers=TEAM
    )
    call_id = r.json()["data"]["callId"]
    rows = (await gateway.client.get("/v1/executions", params={"tool": gateway.tool("get_account")})).json()["data"]
    row = next(x for x in rows["data"] if x["id"] == call_id)
    assert row.get("actingFor"), row
    signed_by_team = row.get("credential") == "team"
    want = {"kind": "team"} if signed_by_team else {"kind": "person", "email": row["actingFor"]}
    assert row["runAs"] == want, row
