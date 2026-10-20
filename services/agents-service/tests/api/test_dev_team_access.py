"""Dev mode keeps acting across teams: the console sends its selected team while the use-case scripts and the seeds
create threads in team_all, so holding dev requests to a team would hide every such thread (platform mode holds it,
tests/api/test_platform_identity.py)."""

from __future__ import annotations

from httpx import AsyncClient


async def test_dev_opens_and_lists_a_thread_from_any_team(client: AsyncClient) -> None:
    created = await client.post(
        "/v1/threads", json={"graph": "simple_workflow", "metadata": {}}, headers={"X-Team-Id": "team_cards"}
    )
    tid = created.json()["data"]["threadId"]
    lending = {"X-Team-Id": "team_lending"}
    assert (await client.get(f"/v1/threads/{tid}/state", headers=lending)).status_code == 200
    listed = (await client.get("/v1/threads", headers=lending)).json()["data"]
    assert tid in [t["threadId"] for t in listed]
