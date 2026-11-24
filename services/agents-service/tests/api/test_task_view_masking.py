"""Who sees a task's personal data, through the real routes with the tokens platform-service mints, by failure mode:
someone who may open a task but not decide it reads the customer's SSN and account id in its fields and details; whoever
holds the decide cell in the task's team sees them masked and cannot check what they approve. The cell is
`reviews.decide` (an Approver's, a Builder's and an Admin's by default); a Viewer opens tasks and holds none."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from ops_service_kit.http import Json
from tests.api.test_action_roles import KEY, REVIEWER
from tests.api.test_case_page import _waiting_with, data, typed_case  # pyright: ignore[reportPrivateUsage]
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.api.test_write_approval_policy import (
    dev_platform,  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
    person,
)
from tests.conftest import sse_events
from tests.engine.test_lifecycle_rights import VIEWER

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
    task, _ = await _task(c)
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


# An Extract from file result whose records name an account id and an SSN, the SSN a number only its field name finds.
_CELL = {"extractedValue": None, "confidence": 0.9, "needsReview": False}
PII_READ: Json = {
    "fileId": "file_scan",
    "floor": 0.8,
    "schema": [
        {"key": "name", "label": "Name", "type": "text"},
        {"key": "accountId", "label": "Account", "type": "text"},
        {"key": "ssn", "label": "SSN", "type": "number"},
    ],
    "records": [
        {
            "values": {"name": "Marcus Bell", "accountId": "BUS-7781", "ssn": 123456789},
            "fields": {
                "accountId": {**_CELL, "value": "BUS-7781", "citation": {"page": 1, "quote": "BUS-7781"}},
                "ssn": {**_CELL, "value": 123456789, "citation": {"page": 1, "quote": "SSN 123456789"}},
            },
        }
    ],
}


async def test_a_viewer_reads_a_waiting_steps_document_read_with_its_account_and_ssn_masked(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    case_id = await typed_case(stack)
    run = await _waiting_with(
        stack, case_id, "pii_read", {"title": "Check the read", "draft": {"document": "scan.pdf", "read": PII_READ}}
    )
    shown = data(await c.get(f"/reviews/{run}", headers=VIEWER))
    assert shown["read"]["records"], shown
    text = json.dumps(shown)
    assert "BUS-7781" not in text and "123456789" not in text, text
    # What says what the read is stays: its file, its field labels and the confidence a person weighs.
    assert shown["read"]["records"][0]["fields"]["ssn"]["confidence"] == 0.9 and "Marcus Bell" in text, text


async def _decided_with_a_correction(s: Stack) -> str:
    """A run's step approved by Maya, an Approver, with the account id corrected and an SSN in her reason."""
    c, _ = s
    run = await _waiting_with(
        s,
        await typed_case(s),
        "pii_task",
        {
            "title": "Check the account",
            "editable": {"path": "$.nodes.lookup.out", "value": {"name": "Marcus Bell", "accountId": "BUS-7781"}},
        },
    )
    fixed = {"name": "Marcus Bell", "accountId": "BUS-9902"}
    body = {"decision": "approved", "inputs": {"edited": fixed}, "reason": "SSN 123-45-6789 matches the file"}
    decided = await c.post(f"/reviews/{run}/decision", json=body, headers=REVIEWER)
    assert decided.status_code == 200, decided.text
    return run


async def test_a_person_who_may_not_decide_a_task_reads_its_decided_values_masked(stack: Stack) -> None:  # noqa: F811
    # GET /v1/tasks/{id} gave a Viewer the corrected account id and the SSN the approver wrote in the reason.
    c, _ = stack
    run = await _decided_with_a_correction(stack)
    shown = data(await c.get(f"/v1/tasks/{run}", headers=VIEWER))
    text = json.dumps(shown)
    assert "BUS-9902" not in text and "123-45-6789" not in text and "[account]" in text, text
    assert shown["status"] == "approved" and shown["id"] == run, shown


async def test_an_api_key_reads_its_tasks_decided_values_as_they_are(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    run = await _decided_with_a_correction(stack)
    shown = data(await c.get(f"/v1/tasks/{run}", headers=KEY))
    assert "BUS-9902" in json.dumps(shown["values"]) and "123-45-6789" in shown["reason"], shown
