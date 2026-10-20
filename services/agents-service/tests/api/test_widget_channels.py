"""An agent's embeds on its Channels tab (c-130), by failure mode: a retired embed still answering its page; a retired
embed resumed or changed; a viewer retiring one; usage counting another embed's or another team's conversations; a
revoked key counted as active."""

from __future__ import annotations

from httpx import AsyncClient

from tests.api.test_widget_embed import (
    BANKER,
    BUILDER,
    INTRANET,
    OUTSIDER,
    VIEWER,
    client,  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
    deploy,
    page,
    session,
    thread,
)


def listed(rows: list[dict[str, object]], dep: str) -> dict[str, object]:
    return next(r for r in rows if r["id"] == dep)


async def test_a_retired_embed_answers_no_page_and_cannot_be_changed(client: AsyncClient) -> None:  # noqa: F811
    dep = (await deploy(client))["id"]
    token = await session(client, dep)
    url = f"/v1/channels/{dep}"
    assert (await client.post(f"{url}/retire", headers=VIEWER)).status_code == 403, "a viewer retires"
    retired = await client.post(f"{url}/retire", headers=BUILDER)
    assert retired.status_code == 200 and retired.json()["data"]["retiredAt"], retired.text
    turn = await client.post(f"/v1/widget/{dep}/threads", headers=page(token))
    assert turn.status_code == 409 and turn.json()["error"]["code"] == "widget_retired", turn.text
    fresh = await client.post(f"/v1/widget/{dep}/session", headers={**BANKER, "Origin": INTRANET})
    assert fresh.status_code == 409 and fresh.json()["error"]["code"] == "widget_retired", fresh.text
    for patch in ({"paused": False}, {"name": "Back again"}, {"origins": ["https://portal.bank.example"]}):
        res = await client.patch(url, json=patch, headers=BUILDER)
        assert res.status_code == 409 and res.json()["error"]["code"] == "widget_retired", (patch, res.text)


async def test_usage_counts_only_the_embeds_own_conversations_and_keys(client: AsyncClient) -> None:  # noqa: F811
    one, two = (await deploy(client))["id"], (await deploy(client))["id"]
    token = await session(client, one)
    for _ in range(2):
        await thread(client, one, token)
    # Another agent's embed in the same team, with a conversation: not one of ag_fraud's, so counted for neither.
    made = await client.post(
        "/v1/widget-deployments",
        json={"name": "Branch help", "agentId": "ag_branch", "origins": [INTRANET]},
        headers=BUILDER,
    )
    branch = made.json()["data"]["id"]
    await thread(client, branch, await session(client, branch))
    keys = [
        (await client.post(f"/v1/widget-deployments/{one}/keys", json={"name": n}, headers=BUILDER)).json()["data"][
            "key"
        ]
        for n in ("server", "old server")
    ]
    revoked = await client.post(f"/v1/widget-deployments/{one}/keys/{keys[1]['id']}/revoke", headers=BUILDER)
    assert revoked.status_code == 200, revoked.text
    rows = (await client.get("/v1/widget-deployments?agentId=ag_fraud", headers=BUILDER)).json()["data"]
    a, b = listed(rows, one), listed(rows, two)
    assert (a["conversations7d"], a["activeKeys"], bool(a["lastUsedAt"])) == (2, 1, True), a
    assert (b["conversations7d"], b["activeKeys"], b.get("lastUsedAt")) == (0, 0, None), b
    other = (await client.get("/v1/widget-deployments", headers=OUTSIDER)).json()["data"]
    assert all(r["id"] not in (one, two) for r in other), "another team does not see the embeds"


CHAT = {"type": "chat", "agentId": "ag_fraud", "name": "Intranet help", "origins": [INTRANET]}


async def test_a_chat_channel_is_created_on_the_channel_api_and_answers_with_its_row(client: AsyncClient) -> None:  # noqa: F811
    """c-339: create is on /v1/channels like every other change, and answers with the row Channels lists."""
    assert (await client.post("/v1/channels", json=CHAT, headers=VIEWER)).status_code == 403, "a viewer creates"
    made = await client.post("/v1/channels", json=CHAT, headers=BUILDER)
    assert made.status_code == 201, made.text
    row = made.json()["data"]
    assert (row["type"], row["serves"]["kind"], row["serves"]["id"]) == ("chat", "agent", "ag_fraud"), row
    assert row["embed"] == {
        "agentId": "ag_fraud",
        "agentVersion": row["serves"]["version"],
        "origins": [INTRANET],
        "retiredAt": None,
        "activeKeys": 0,
    }, row
    # The deprecated alias still makes the same record.
    body = {k: v for k, v in CHAT.items() if k != "type"}
    alias = await client.post("/v1/widget-deployments", json=body, headers=BUILDER)
    assert alias.status_code == 201, alias.text


async def test_an_agents_embeds_list_on_the_channel_api_with_usage_keys_and_retired_ones_on_request(
    client: AsyncClient,  # noqa: F811
) -> None:
    """c-339: GET /v1/channels?type=chat&agentId= carries what the embed table shows; retired embeds only when asked."""
    one = (await client.post("/v1/channels", json=CHAT, headers=BUILDER)).json()["data"]["id"]
    two = (await client.post("/v1/channels", json=CHAT, headers=BUILDER)).json()["data"]["id"]
    other = await client.post("/v1/channels", json=CHAT | {"agentId": "ag_branch"}, headers=BUILDER)
    token = await session(client, one)
    for _ in range(2):
        await thread(client, one, token)
    await client.post(f"/v1/widget-deployments/{one}/keys", json={"name": "server"}, headers=BUILDER)
    assert (await client.post(f"/v1/channels/{two}/retire", headers=BUILDER)).status_code == 200
    url = "/v1/channels?type=chat&agentId=ag_fraud"
    live = (await client.get(url, headers=BUILDER)).json()["data"]
    rows = {r["id"]: r for r in live["data"]}
    assert set(rows) == {one}, "a retired embed and another agent's are left out"
    a = rows[one]
    assert (a["embed"]["activeKeys"], a["activity7d"], bool(a["lastActivityAt"])) == (1, 2, True), a
    every = (await client.get(url + "&includeRetired=true", headers=BUILDER)).json()["data"]
    retired = next(r for r in every["data"] if r["id"] == two)
    assert retired["embed"]["retiredAt"] and retired["health"]["reason"] == "Retired", retired
    assert other.json()["data"]["id"] not in {r["id"] for r in every["data"]}
    chat = next(k for k in every["kinds"] if k["type"] == "chat")
    assert chat["total"] == 2, "kinds count live channels only: one and ag_branch's"
