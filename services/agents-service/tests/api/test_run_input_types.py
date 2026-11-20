"""A run's input held to the types its trigger declares, by failure mode: text that is no number reaches a number
compare, which reads false and takes the wrong branch; a number sent as text ("120" from a CLI flag, a form field or a
spreadsheet cell) is compared as text; text a field declares as text is turned into a number; a batch stores a row
whose input its workflow refuses. Real routes on the app with its own database; Files is faked at its routes."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from tests.api.test_batches import tick, wired
from tests.api.test_forms import flow, runs_of
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER

WID = "refund_request"
INPUTS = {
    "type": "object",
    "required": ["amount"],
    "properties": {
        "amount": {"type": "number", "title": "Amount"},
        "postcode": {"type": "string", "title": "Postcode"},
        "urgent": {"type": "boolean", "title": "Urgent"},
    },
}


async def live(c: AsyncClient) -> None:
    made = await c.post("/v1/workflows/definitions", json={"definition": flow(WID, INPUTS)}, headers=BUILDER)
    assert made.status_code == 201, made.text
    published = await c.post(f"/v1/workflows/definitions/{WID}/publish-requests", json={}, headers=BUILDER)
    assert published.status_code == 201, published.text


async def start(c: AsyncClient, values: dict[str, Any]) -> Any:
    return await c.post("/v1/runs", json={"workflowId": WID, "input": values}, headers=BUILDER)


async def test_text_for_a_number_is_refused_naming_the_field_and_the_reason(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await live(c)
    refused = await start(c, {"amount": "a lot"})
    assert refused.status_code == 422, refused.text
    error = refused.json()["error"]
    assert error["code"] == "invalid_input" and error["details"]["path"] == "amount", error
    assert "number" in error["details"]["reason"] and "Amount" in error["message"], error
    assert await runs_of(c, WID) == []


async def test_a_number_sent_as_text_is_stored_as_the_number_and_text_stays_text(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await live(c)
    started = await start(c, {"amount": "120", "postcode": "01234", "urgent": "true"})
    assert started.status_code == 202, started.text
    got = (await c.get(f"/v1/runs/{started.json()['data']['runId']}", headers=BUILDER)).json()["data"]
    assert got["input"] == {"amount": 120, "postcode": "01234", "urgent": True}, got["input"]


async def test_a_batch_reads_each_cell_as_its_type_and_refuses_the_file_naming_the_bad_row(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    rt, files = wired(c)
    await live(c)

    def stored(fid: str, body: str) -> str:
        files.stored[fid] = {
            "id": fid, "name": "refunds.csv", "mime": "text/csv", "size": len(body), "digest": "d",
            "purpose": "case_attachment", "team": "team_ops", "uploadedBy": "james@harborpine.example",
            "scan": {"status": "clean"}, "bytes": body.encode(),
        }  # fmt: skip
        return fid

    async def batch(fid: str) -> Any:
        return await c.post(f"/v1/workflows/{WID}/batches", json={"fileId": fid, "mode": "live"}, headers=BUILDER)

    bad = await batch(stored("file_bad", "Amount,Postcode\n120,01234\nabout 40,90210\n"))
    assert bad.status_code == 422, bad.text
    error = bad.json()["error"]
    assert (error["code"], error["details"]["row"], error["details"]["path"]) == ("invalid_input", 2, "amount"), error
    await tick(rt)
    assert await runs_of(c, WID) == [], "a refused file starts no row"

    good = await batch(stored("file_good", "Amount,Postcode\n120,01234\n"))
    assert good.status_code in (200, 202), good.text
    assert await tick(rt) == 1
    [run] = await runs_of(c, WID)
    got = (await c.get(f"/v1/runs/{run['id']}", headers=BUILDER)).json()["data"]
    assert got["input"] == {"amount": 120, "postcode": "01234"}, got["input"]


async def test_digits_too_long_to_read_as_a_number_are_refused_naming_the_field(stack: Stack) -> None:  # noqa: F811
    """Python refuses to read more than 4,300 digits as a number; that must be the caller's 422, not a 500."""
    c, _ = stack
    await live(c)
    refused = await start(c, {"amount": "9" * 5000})
    assert refused.status_code == 422, refused.text[:300]
    error = refused.json()["error"]
    assert error["code"] == "invalid_input" and error["details"]["path"] == "amount", error
