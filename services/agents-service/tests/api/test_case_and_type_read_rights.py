"""Reading cases, batches and task and case types without the view cell, by failure mode: each GET asked only for a
signed-in person, so a chat user read the team's cases (customer names included), a batch's rows and every type; and
the check that closes them must still let a viewer read."""

from __future__ import annotations

from httpx import AsyncClient

from tests.api.test_batches import batch, csv, ready, wired
from tests.api.test_case_page import typed_case
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import VIEWER, person

CHAT_USER = person("lena", "team_ops", "chat_user")


async def refused(c: AsyncClient, *paths: str) -> None:
    for path in paths:
        got = await c.get(path, headers=CHAT_USER)
        assert got.status_code == 403, (path, got.status_code, got.text[:200])
        assert got.json()["error"]["code"] == "forbidden", (path, got.text)


async def read(c: AsyncClient, path: str) -> None:
    got = await c.get(path, headers=VIEWER)
    assert got.status_code == 200, (path, got.text)


async def test_a_chat_user_reads_no_case_run_and_a_viewer_reads_the_list(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await read(c, "/runs")
    await refused(c, "/runs", "/runs/thread_1")


async def test_a_chat_user_reads_no_case_record_and_a_viewer_reads_one(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    case_id = await typed_case(stack, customer="C-lena")
    await read(c, f"/v1/cases/{case_id}")
    await refused(c, "/v1/cases", f"/v1/cases/{case_id}")


async def test_a_chat_user_reads_no_batch_and_a_viewer_reads_its_rows(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    _, files = wired(c)
    started = await batch(c, await ready(c, files, csv(2)))
    assert started.status_code == 202, started.text
    batch_id = started.json()["data"]["id"]
    await read(c, f"/v1/batches/{batch_id}")
    await read(c, f"/v1/batches/{batch_id}/results.csv")
    await refused(c, f"/v1/batches/{batch_id}", f"/v1/batches/{batch_id}/results.csv")


async def test_a_chat_user_reads_no_task_or_case_type_and_a_viewer_reads_them(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    for path in ("/v1/task-types", "/v1/task-types/write_approval", "/v1/case-types", "/v1/case-types/complaint"):
        await read(c, path)
    await refused(c, "/v1/task-types", "/v1/task-types/write_approval", "/v1/case-types", "/v1/case-types/complaint")
