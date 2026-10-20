"""The review queue reads a chat thread's checkpoint only when the thread can hold a review (tick 36), by failure mode:
every chat thread of the team is resolved and its state read on each list, so the queue costs a checkpoint read per
conversation ever held; and a thread that is waiting on an approval is skipped and its review goes missing."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from ops_agents.api import hitl_facade
from tests.api.test_write_approval_policy import dev_platform, drafted, person  # noqa: F401  # pyright: ignore[reportUnusedImport]


async def test_the_queue_reads_only_threads_that_can_hold_a_review(
    dev_platform: AsyncClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    james = person("usr_james", ["team_ops"])
    for _ in range(4):
        res = await dev_platform.post("/chat/threads", json={"agentId": "ag_dispute", "kbIds": []}, headers=james)
        thread = res.json()["data"]["id"]
        said = await dev_platform.post(
            f"/chat/threads/{thread}/messages",
            json={"content": "hello"},
            headers={**james, "Accept": "text/event-stream"},
        )
        assert said.status_code == 200, said.text
    held = (await drafted(dev_platform, james)).split("/")[3]
    resolved: list[str] = []
    real = hitl_facade.resolve

    async def counting(rt: Any, thread_id: str) -> Any:
        resolved.append(thread_id)
        return await real(rt, thread_id)

    monkeypatch.setattr(hitl_facade, "resolve", counting)
    listed = (await dev_platform.get("/reviews", params={"view": "open", "pageSize": 100}, headers=james)).json()
    assert held in {r["id"] for r in listed["data"]["data"]}, listed
    # The held thread is resolved to list it and again to draw its review; no idle thread is resolved at all.
    assert set(resolved) == {held}, resolved
