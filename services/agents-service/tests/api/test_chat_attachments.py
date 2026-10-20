"""Files attached to a chat message, by failure mode: an attachment the model never reads; an answer that does not
cite the file it came from; a type or size chat cannot read accepted; another person's file read by id; a file cut
for length without saying so."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from ops_agents.activities import attachments
from ops_agents.api.deps import Runtime
from tests.api.test_chat import new_thread, send
from tests.api.test_chat_on_graph import stack  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixture
from tests.api.test_write_approval_policy import (
    dev_platform,  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixture
    person,
)

PDF = (Path(__file__).parents[3] / "kb-service/seed/pdfs/fee-schedule-v2.pdf").read_bytes()
ASK = "What does a replacement debit card cost?"


async def upload(client: AsyncClient, data: bytes, name: str, mime: str, **kw: Any) -> Any:
    return await client.post(
        "/chat/attachments", params={"name": name}, content=data, headers={"Content-Type": mime}, **kw
    )


async def test_an_attached_pdf_is_read_and_its_page_is_cited(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, _ = stack
    made = await upload(client, PDF, "fees.pdf", "application/pdf")
    assert made.status_code == 201, made.text
    file = made.json()["data"]
    tid = (await new_thread(client, kb_ids=["kb_people"]))["id"]
    _, events = await send(client, tid, {"content": ASK, "attachments": [file]})
    cited = next(e["citations"] for e in events if e["type"] == "citations")
    assert cited[0]["title"] == "fees.pdf" and cited[0]["page"] == 3, cited
    assert "replacement debit card" in cited[0]["snippet"].lower()
    reply = events[-1]["message"]
    assert reply["citations"][0]["documentId"] == file["fileId"] and "[1]" in reply["content"]


async def test_a_type_or_size_chat_cannot_read_is_refused_saying_what_it_reads(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    client, _ = stack
    exe = await upload(client, b"MZ\x90\x00", "setup.exe", "application/octet-stream")
    assert (
        exe.status_code == 422 and "PDF" in exe.json()["error"]["message"] and "10 MB" in exe.json()["error"]["message"]
    )
    big = await upload(client, b"a" * (attachments.MAX_BYTES + 1), "huge.txt", "text/plain")
    assert big.status_code == 422 and "larger than 10 MB" in big.json()["error"]["message"]


async def test_another_persons_file_is_not_found(dev_platform: AsyncClient) -> None:  # noqa: F811
    james, maya = person("usr_james", ["team_ops"]), person("usr_maya", ["team_ops"])
    made = await dev_platform.post(
        "/chat/attachments",
        params={"name": "fees.pdf"},
        content=PDF,
        headers={**james, "Content-Type": "application/pdf"},
    )
    assert made.status_code == 201, made.text
    file = made.json()["data"]
    tid = (await dev_platform.post("/chat/threads", json={"agentId": "ag_dispute", "kbIds": []}, headers=maya)).json()[
        "data"
    ]["id"]
    res = await dev_platform.post(
        f"/chat/threads/{tid}/messages", json={"content": ASK, "attachments": [file]}, headers=maya
    )
    assert res.status_code == 404, res.text


async def test_a_file_cut_for_length_says_so_in_the_reply(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = stack
    monkeypatch.setattr(attachments, "TURN_TEXT_CHARS", 300)
    file = (await upload(client, PDF, "fees.pdf", "application/pdf")).json()["data"]
    tid = (await new_thread(client))["id"]
    _, events = await send(client, tid, {"content": ASK, "attachments": [file]})
    assert "Only part of fees.pdf was read" in events[-1]["message"]["content"]
    reloaded = (await client.get(f"/chat/threads/{tid}")).json()["data"]["messages"][-1]
    assert "Only part of fees.pdf was read" in reloaded["content"], "a reload says the same"
