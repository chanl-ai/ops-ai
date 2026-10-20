"""SSO step-up: the identity provider's callback code buys a signed step-up only for the account it confirmed."""

from __future__ import annotations

import base64

from httpx import AsyncClient

from tests.api.test_chat import new_thread, send

DEV = "j.richardson@northfieldbank.com"


def code_for(email: str) -> str:
    return base64.b64encode(email.encode()).decode()


async def test_sso_callback_for_the_caller_mints_a_step_up_money_decisions_accept(client: AsyncClient) -> None:
    res = await client.post("/v1/auth/step-up/sso", json={"code": code_for(DEV)})
    assert res.status_code == 200, res.text
    token = res.json()["data"]["token"]
    thread = await new_thread(client)
    _, events = await send(client, thread["id"], {"content": "Place a 24-hour hold on wire W-88213"})
    widget = next(e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval")
    url = f"/chat/threads/{thread['id']}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"
    approved = await client.post(url, json={"type": "approve", "stepUpToken": token})
    assert approved.status_code == 200, approved.text


async def test_sso_callback_for_another_account_is_refused(client: AsyncClient) -> None:
    res = await client.post("/v1/auth/step-up/sso", json={"code": code_for("someone.else@northfieldbank.com")})
    assert res.status_code == 401
    garbled = await client.post("/v1/auth/step-up/sso", json={"code": "%%%not-base64"})
    assert garbled.status_code == 401
