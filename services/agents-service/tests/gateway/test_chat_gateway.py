"""Chat with the tool gateway on: a money action asked for in chat runs only on the review service's real approval
token, minted once two different people have approved it in the chat widget."""

from __future__ import annotations

import httpx

from tests.api.test_chat import new_thread, send
from tests.conftest import step_up
from tests.gateway.conftest import Gateway
from tests.gateway.test_dispute_e2e import apps, runtime  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixtures

LEE = "lee@northfieldbank.com"


async def test_a_chat_two_approver_action_runs_on_two_approvals_through_the_gateway(
    runtime: httpx.AsyncClient,  # noqa: F811
    gateway: Gateway,
) -> None:
    thread = await new_thread(runtime)
    _, events = await send(runtime, thread["id"], {"content": "Place a 24-hour hold on wire W-88213"})
    widget = next(e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval")
    url = f"/chat/threads/{thread['id']}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"

    first = await runtime.post(url, json={"type": "approve", "stepUpToken": await step_up(runtime)})
    assert first.status_code == 200, first.text
    assert first.json()["data"]["state"] == "awaiting_second"
    assert await gateway.log.for_thread(thread["id"], tenant_id="local") == []  # nothing ran on one approval

    second = await runtime.post(
        url, json={"type": "approve", "stepUpToken": await step_up(runtime, LEE)}, headers={"X-Dev-User": LEE}
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"]["state"] == "approved"
    rows = await gateway.log.for_thread(thread["id"], tenant_id="local")
    assert [(r["tool"], r["decision"], r["outcome"]) for r in rows] == [("place_wire_hold", "allow", "ok")]
    reply = (await runtime.get(f"/chat/threads/{thread['id']}")).json()["data"]["messages"][-1]
    assert "hold is in place" in reply["content"]
