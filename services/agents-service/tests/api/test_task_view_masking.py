"""Who sees a task's personal data, through the real routes with the tokens platform-service mints, by failure mode:
someone who may open a task but not decide it reads the customer's SSN and account id in its fields and details; whoever
holds the decide cell in the task's team sees them masked and cannot check what they approve. The cell is
`reviews.decide` (an Approver's, a Builder's and an Admin's by default); a Viewer opens tasks and holds none."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from tests.api.test_write_approval_policy import (
    dev_platform,  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
    person,
)
from tests.conftest import sse_events

ASK = (
    'call request_document {"customerId": "C-1042", "accountId": "BUS-7781", "document": "proof of address",'
    ' "reason": "SSN 123-45-6789 on file"}'
)
REAL = ("BUS-7781", "123-45-6789")


async def _task(c: AsyncClient) -> tuple[str, str]:
    """A write James, a Viewer, asked for in chat, waiting for a person in team_ops: its id and its approval URL."""
    james = person("usr_james", ["team_ops"], role="viewer")
    thread = (await c.post("/chat/threads", json={"agentId": "ag_dispute", "kbIds": []}, headers=james)).json()["data"]
    sent = await c.post(
        f"/chat/threads/{thread['id']}/messages",
        json={"content": ASK},
        headers={**james, "Accept": "text/event-stream"},
    )
    assert sent.status_code == 200, sent.text
    events = sse_events(sent.text)
    widget = next(e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval")
    url = f"/chat/threads/{thread['id']}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"
    return str(thread["id"]), url


@pytest.mark.parametrize(("role", "decides"), [("viewer", False), ("approver", True), ("admin", True)])
async def test_only_who_may_decide_a_task_sees_its_real_values(
    dev_platform: AsyncClient,  # noqa: F811
    role: str,
    decides: bool,
) -> None:
    c = dev_platform
    task, url = await _task(c)
    reader = person(f"usr_{role}", ["team_ops"], role=role)
    one = await c.get(f"/reviews/{task}", headers=reader)
    listed = await c.get("/reviews", headers=reader)
    assert one.status_code == 200 and listed.status_code == 200, (one.text, listed.text)
    rows = [r for r in listed.json()["data"]["data"] if r["id"] == one.json()["data"]["id"]]
    assert rows, listed.text
    for shown in (json.dumps(one.json()["data"]), json.dumps(rows)):
        if decides:
            assert all(v in shown for v in REAL), shown
        else:
            assert not any(v in shown for v in REAL) and "[account]" in shown and "[SSN]" in shown, shown
            # What names the task stays readable: its id, its customer's id and its deciding team.
            assert task in shown and "C-1042" in shown and "team_ops" in shown, shown
    if not decides:
        # Once decided the task is read from its stored review; it stays masked for whoever may not decide it.
        approved = await c.post(url, json={"type": "approve"}, headers=person("usr_maya", ["team_ops"]))
        assert approved.status_code == 200, approved.text
        after = json.dumps((await c.get(f"/reviews/{task}", headers=reader)).json())
        assert not any(v in after for v in REAL) and "[account]" in after, after
