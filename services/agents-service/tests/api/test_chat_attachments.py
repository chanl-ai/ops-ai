"""Files attached to a chat message, read through files-service and documents-service, by failure mode: the file's
text never reaching the model; the model not told the file's name and id; a file with no text answered as if read;
another team's file read by id; an earlier file gone from Files stopping the conversation; a file cut for length
without saying so; a file attached in chat kept from being deleted in Files; a message with files answered without
them where Files is not run. files-service and documents-service are their clients' fakes."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from ops_agents.activities import attachments
from ops_agents.api.chat_attachments import ChatAttachmentReader
from ops_agents.api.chat_threads import chat_row
from ops_agents.api.deps import Runtime
from ops_documents_client.testing import FakeDocumentsService
from ops_files_client.testing import FakeFilesService
from tests.api.test_chat import new_thread, send
from tests.api.test_chat_on_graph import stack  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixture

ASK = "What does a replacement debit card cost?"
FEES = ["Schedule of fees, effective 2026.", "Account fees: monthly fee waived.", "Replacement debit card: $10."]


class Rig:
    def __init__(self, rt: Runtime) -> None:
        self.files, self.documents = FakeFilesService(), FakeDocumentsService()
        rt.chat_attachments = ChatAttachmentReader(
            self.files.client(service="agents", scopes=["files:view"]), self.documents.client(), wait_s=0
        )
        self.rt = rt

    async def team(self, tid: str) -> str:
        row = await chat_row(self.rt, tid, None)
        assert row is not None
        return str(row["team_id"])

    async def put(self, team: str, name: str, pages: list[str] | None, *, tenant: str = "local") -> dict[str, Any]:
        writer = self.files.client(service="kb", scopes=["files:view", "files:create"])
        stored = await writer.write(
            tenant, team, name.encode() + b"\n", name=name, mime="application/pdf", purpose="chat_attachment",
            uploaded_by="james",
        )  # fmt: skip
        self.files.files[stored.file.id]["scan"] = {"status": "clean"}
        if pages is not None:
            self.documents.pages[stored.file.id] = pages
        return {"fileId": stored.file.id, "name": name, "size": stored.file.size}


@pytest.fixture
def rig(stack: tuple[AsyncClient, Runtime]) -> Rig:  # noqa: F811
    return Rig(stack[1])


async def thread_and_file(client: AsyncClient, rig: Rig, name: str, pages: list[str] | None) -> tuple[str, Any]:
    tid = (await new_thread(client, kb_ids=["kb_people"]))["id"]
    return tid, await rig.put(await rig.team(tid), name, pages)


async def test_an_attached_files_text_is_read_and_its_page_is_cited(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
    rig: Rig,
) -> None:
    client, _ = stack
    tid, file = await thread_and_file(client, rig, "fees.pdf", FEES)
    _, events = await send(client, tid, {"content": ASK, "attachments": [file]})
    cited = next(e["citations"] for e in events if e["type"] == "citations")
    assert cited[0]["title"] == "fees.pdf" and cited[0]["page"] == 3, cited
    # The citation names the file, so the console opens it in Files rather than as a knowledge item.
    assert cited[0]["fileId"] == file["fileId"], cited
    assert "replacement debit card" in cited[0]["snippet"].lower()
    reply = events[-1]["message"]
    first = reply["citations"][0]
    assert first["documentId"] == file["fileId"] and f"[{first['n']}]" in reply["content"], reply


async def test_the_agent_is_told_each_attached_files_name_and_id(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
    rig: Rig,
) -> None:
    client, _ = stack
    tid, file = await thread_and_file(client, rig, "fees.pdf", FEES)
    _, events = await send(client, tid, {"content": "What did I attach?", "attachments": [file]})
    assert f"fees.pdf ({file['fileId']})" in events[-1]["message"]["content"], events[-1]


async def test_a_file_with_no_text_is_told_to_the_agent_and_the_person(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
    rig: Rig,
) -> None:
    client, _ = stack
    tid, scan = await thread_and_file(client, rig, "scan.pdf", None)
    _, events = await send(client, tid, {"content": "What did I attach?", "attachments": [scan]})
    content = events[-1]["message"]["content"]
    assert f"scan.pdf ({scan['fileId']}): could not be read: it has no text to read" in content, content
    assert "_scan.pdf could not be read: it has no text to read" in content, "the person is told too"


async def test_another_teams_file_is_not_found(stack: tuple[AsyncClient, Runtime], rig: Rig) -> None:  # noqa: F811
    client, _ = stack
    tid = (await new_thread(client))["id"]
    theirs = await rig.put("team_elsewhere", "fees.pdf", FEES)
    res = await client.post(f"/chat/threads/{tid}/messages", json={"content": ASK, "attachments": [theirs]})
    assert res.status_code == 404 and theirs["fileId"] in res.json()["error"]["message"], res.text
    assert rig.documents.reads == 0


async def test_an_earlier_file_gone_from_files_is_told_and_the_conversation_goes_on(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
    rig: Rig,
) -> None:
    client, _ = stack
    tid, file = await thread_and_file(client, rig, "fees.pdf", FEES)
    await send(client, tid, {"content": ASK, "attachments": [file]})
    del rig.files.files[file["fileId"]]
    _, events = await send(client, tid, {"content": "What did I attach?"})
    content = events[-1]["message"]["content"]
    assert f"fees.pdf ({file['fileId']}): could not be read: it is no longer in Files" in content, content


async def test_a_file_cut_for_length_says_so_in_the_reply(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = stack
    monkeypatch.setattr(attachments, "TURN_TEXT_CHARS", 60)
    tid, file = await thread_and_file(client, rig, "fees.pdf", FEES)
    _, events = await send(client, tid, {"content": ASK, "attachments": [file]})
    assert "Only part of fees.pdf was read" in events[-1]["message"]["content"]
    reloaded = (await client.get(f"/chat/threads/{tid}")).json()["data"]["messages"][-1]
    assert "Only part of fees.pdf was read" in reloaded["content"], "a reload says the same"


async def test_a_file_attached_in_chat_can_still_be_deleted_from_files(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
    rig: Rig,
) -> None:
    client, _ = stack
    tid, file = await thread_and_file(client, rig, "fees.pdf", FEES)
    await send(client, tid, {"content": ASK, "attachments": [file]})
    # files-service refuses to delete a file while anything references it; a conversation holds none.
    assert not rig.files.references.get(file["fileId"]), rig.files.references


async def test_a_message_with_files_is_refused_where_files_is_not_run(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
    rig: Rig,
) -> None:
    client, rt = stack
    tid, file = await thread_and_file(client, rig, "fees.pdf", FEES)
    rt.chat_attachments = None
    res = await client.post(f"/chat/threads/{tid}/messages", json={"content": ASK, "attachments": [file]})
    assert res.status_code == 503 and "Files" in res.json()["error"]["message"], res.text


async def test_a_long_attached_file_reaches_the_model_whole_and_is_read_with_ocr(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
    rig: Rig,
) -> None:
    """Six pages of 2,500 characters: more than the 3 pieces of 2,000 a knowledge search returns, inside the turn's
    share, so all of it reaches the model. A scan's text exists only when the reading ran OCR."""
    client, _ = stack
    pages = [f"Page {n} of the contract. " + "clause " * 350 for n in range(1, 7)]
    tid, file = await thread_and_file(client, rig, "contract.pdf", pages)
    _, events = await send(client, tid, {"content": "How many pages did you get?", "attachments": [file]})
    reply = events[-1]["message"]["content"]
    assert reply.startswith("6 pages,") and int(reply.split(", ")[1].split()[0]) > 6_000, reply
    assert {ocr for _, ocr in rig.documents.readings} == {"auto"}, rig.documents.readings
