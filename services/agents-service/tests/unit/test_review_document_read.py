"""Human Tasks shows a document read and the reply a review approves (c-169), by failure mode: the read shown as raw
JSON (no typed `read`, the proposal a dumped dict), a correction lost from the decided review, the acknowledgement
naming cases of runs it did not start or none for a run that has its case, and a review with neither breaking."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ops_agents.api import engine_reviews

FIELD = {"value": None, "extractedValue": None, "confidence": 1.0, "needsReview": False, "citation": None}
READ: dict[str, Any] = {
    "fileId": "file_scan",
    "floor": 0.8,
    "count": 1,
    "needsReview": [0],
    "schema": [
        {"key": "name", "label": "Name", "type": "text", "required": True},
        {"key": "address", "label": "Address", "type": "text", "required": False},
    ],
    "records": [
        {
            "values": {"name": "Priya Natarajan", "address": "ON Mav: 1A5"},
            "fields": {
                "name": {
                    **FIELD,
                    "value": "Priya Natarajan",
                    "confidence": 0.63,
                    "citation": {"fileId": "file_scan", "page": 1, "quote": "Priya Natarajan"},
                },
                "address": {
                    **FIELD,
                    "value": "ON Mav: 1A5",
                    "confidence": 0.42,
                    "needsReview": True,
                    "citation": {"fileId": "file_scan", "page": 1, "quote": "ON Mav: 1A5"},
                },
            },
            "needsReview": ["address"],
        }
    ],
}
CHECK: dict[str, Any] = {
    "node": "check",
    "step_id": "wfrun_doc:check:1",
    "title": "Check the debtors read from the document",
    "draft": {"document": "levy_notice_scan.pdf", "read": READ},
    "editable": {"path": "$.nodes.read.out.records", "value": READ["records"]},
}
# The view reads the database only for cases, which these tests answer themselves.


class _NoTools:
    async def operations(self) -> list[Any]:
        return []


def _no_card(_name: str) -> None:
    return None


RT: Any = SimpleNamespace(db=None, catalog=SimpleNamespace(tool=_no_card), directory=_NoTools)


@pytest.fixture(autouse=True)
def _no_task_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """These reviews name no task type, so view draws them through a seeded one from the database (legacy_tasks),
    which RT has none of; the review's own fields are what these tests read, and test_legacy_tasks reads the task."""

    async def none(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(engine_reviews, "legacy_task", none)


TITLES: dict[str, Any] = {
    "workflow": "Mailed document",
    "steps": {"check": "Check the read", "ack": "Send the acknowledgement"},
}
RUN: dict[str, Any] = {
    "id": "wfrun_doc",
    "team_id": "team_ops",
    "workflow_id": "mail_document",
    "version": 3,
    "updated_at": "now",
    "status": "waiting",
}


async def test_a_read_check_carries_the_file_each_fields_label_confidence_and_quote() -> None:
    review = await engine_reviews.view(RT, {**RUN, "waiting": {"payload": CHECK}}, case_id="", titles=TITLES)
    read = review["read"]
    assert (read["fileId"], read["fileName"], read["floor"], read["editable"]) == (
        "file_scan",
        "levy_notice_scan.pdf",
        0.8,
        True,
    )
    assert [(f["key"], f["label"]) for f in read["schema"]] == [("name", "Name"), ("address", "Address")]
    address = read["records"][0]["fields"]["address"]
    assert (address["confidence"], address["needsReview"], address["citation"]) == (
        0.42,
        True,
        {"page": 1, "quote": "ON Mav: 1A5"},
    )
    assert review["customer"] == "Priya Natarajan"
    # Named for the sheet by the workflow and step, linking to the run, never by the raw step id.
    assert (review["workflowName"], review["workflowVersion"], review["stepName"], review["runId"]) == (
        "Mailed document",
        3,
        "Check the read",
        "wfrun_doc",
    )
    assert review["proposal"] == "Read 1 record from levy_notice_scan.pdf; 1 field to check", review["proposal"]


async def test_a_read_check_carries_each_fields_boxes_so_the_task_page_can_draw_them() -> None:
    box = {"page": 1, "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.04}
    fields = READ["records"][0]["fields"]
    address = {**fields["address"], "boxes": [box, {"page": "one"}]}
    records = [{**READ["records"][0], "fields": {**fields, "address": address}}]
    check = {**CHECK, "draft": {**CHECK["draft"], "read": {**READ, "records": records}}}
    review = await engine_reviews.view(RT, {**RUN, "waiting": {"payload": check}}, case_id="", titles=TITLES)
    got = review["read"]["records"][0]["fields"]
    # A box the page cannot place (no numeric page) is dropped rather than drawn at the top left.
    assert (got["address"]["boxes"], got["name"]["boxes"]) == ([box], [])


async def test_a_read_check_whose_step_names_the_file_under_file_shows_that_name() -> None:
    check = {**CHECK, "draft": {"file": "TEST012.pdf", "read": READ}}
    review = await engine_reviews.view(RT, {**RUN, "waiting": {"payload": check}}, case_id="", titles=TITLES)
    assert review["read"]["fileName"] == "TEST012.pdf"


async def test_a_field_the_document_type_marks_key_is_marked_key_in_the_check() -> None:
    schema = [{**READ["schema"][0], "keyField": True}, READ["schema"][1]]
    check = {**CHECK, "draft": {**CHECK["draft"], "read": {**READ, "schema": schema}}}
    review = await engine_reviews.view(RT, {**RUN, "waiting": {"payload": check}}, case_id="", titles=TITLES)
    assert [(f["key"], f["keyField"]) for f in review["read"]["schema"]] == [("name", True), ("address", False)]


async def test_a_read_combined_with_another_source_shows_each_sources_value_and_marks_the_disagreement() -> None:
    combined = {
        "values": {"name": "Priya Natarajan", "address": "ON Mav: 1A5"},
        "sources": {"name": "document", "address": "document"},
        "conflicts": [
            {
                "field": "name",
                "values": [
                    {"source": "document", "value": "Priya Natarajan"},
                    {"source": "email", "value": {"value": "P. Natarajan", "confidence": 0.9}},
                ],
            }
        ],
        "hasConflicts": True,
    }
    one = {**READ, "records": READ["records"][:1]}
    check = {**CHECK, "draft": {"document": "levy_notice_scan.pdf", "read": one, "facts": combined}}
    review = await engine_reviews.view(RT, {**RUN, "waiting": {"payload": check}}, case_id="", titles=TITLES)
    read = review["read"]
    fields = read["records"][0]["fields"]
    assert read["sources"] == ["document", "email"]
    assert (fields["name"]["bySource"], fields["name"]["conflict"]) == (
        {"document": "Priya Natarajan", "email": "P. Natarajan"},
        True,
    )
    # A field the sources agree on shows the one it was taken from, and no disagreement.
    assert (fields["address"]["bySource"], fields["address"]["conflict"]) == ({"document": "ON Mav: 1A5"}, False)


async def test_a_read_of_one_source_has_no_sources() -> None:
    review = await engine_reviews.view(RT, {**RUN, "waiting": {"payload": CHECK}}, case_id="", titles=TITLES)
    assert review["read"]["sources"] == [] and "bySource" not in review["read"]["records"][0]["fields"]["name"]


async def test_a_decided_check_keeps_the_corrected_values_it_was_approved_with() -> None:
    fixed = [{"values": {"name": "Priya Natarajan", "address": "18 Oak Avenue, Toronto ON M4V 1A5"}}]
    decided = {"payload": CHECK, "resume": {"decision": "approved", "edited": fixed}, "at": "now"}
    review = await engine_reviews.view(RT, RUN, decided, case_id="", titles=TITLES)
    assert review["status"] == "approved"
    assert review["read"]["corrected"] == [fixed[0]["values"]]
    # The read's own values stay as read, so the sheet shows what was corrected from what.
    assert review["read"]["records"][0]["values"]["address"] == "ON Mav: 1A5"


ACK: dict[str, Any] = {
    "node": "ack",
    "step_id": "wfrun_doc:ack:1",
    "title": "Acknowledge the document",
    "draft": {
        "document": "levy_notice.pdf",
        "to": "clerk@court.example",
        "cases": {
            "workflowId": "levy_case",
            "count": 2,
            "runs": [{"index": 0, "runId": "wfrun_a"}, {"index": 1, "runId": "wfrun_b"}],
        },
    },
    "call": {
        "tool": "send_reply",
        "input": {
            "to": "clerk@court.example",
            "subject": "Levy notice",
            "body": "We received your document.",
            "mailbox": "intake@harborpine.test",
        },
    },
}


class Cases:
    """The case each run is on: wfrun_a has opened its case, wfrun_b not yet; wfrun_other is another document's."""

    def __init__(self, _db: Any) -> None: ...

    async def cases_of_runs(self, run_ids: list[str]) -> dict[str, str]:
        on = {"wfrun_a": "case_7", "wfrun_other": "case_9"}
        return {r: on[r] for r in run_ids if r in on}

    async def get(self, case_id: str, _teams: list[str]) -> dict[str, Any]:
        return {"id": case_id, "subject": "Levy notice: Ana Example (NS-2026-GN-09999)"}


async def test_an_acknowledgement_shows_the_reply_and_the_case_each_started_run_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_reviews, "CaseStore", Cases)
    monkeypatch.setattr(engine_reviews, "policy_of", _policy)
    review = await engine_reviews.view(RT, {**RUN, "waiting": {"payload": ACK}}, case_id="", titles=TITLES)
    assert review["reply"] == {
        "to": "clerk@court.example",
        "mailbox": "intake@harborpine.test",
        "subject": "Levy notice",
        "body": "We received your document.",
        # A case reads by its subject, so the page never shows the id to decide on.
        "cases": [
            {"runId": "wfrun_a", "caseId": "case_7", "subject": "Levy notice: Ana Example (NS-2026-GN-09999)"},
            {"runId": "wfrun_b", "caseId": None, "subject": None},
        ],
    }
    assert "read" not in review


async def _policy(_rt: Any, _tool: str) -> Any:
    return SimpleNamespace(approvers=1, access="write", step_up=False)


async def test_a_review_with_no_read_and_no_reply_has_neither() -> None:
    payload = {"node": "check", "step_id": "wfrun_1:check:1", "draft": {"record": {"name": "Marcus Bell"}}}
    review = await engine_reviews.view(RT, {**RUN, "waiting": {"payload": payload}}, case_id="", titles=TITLES)
    assert ("read" in review, "reply" in review) == (False, False)
    assert review["customer"] == "Marcus Bell"
