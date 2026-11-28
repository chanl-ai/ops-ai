"""The client reads every page of the team's document types, so a type past the first page is still found by name;
and a 503 reads as unreachable, so a knowledge sync waits instead of failing the file for good."""

from __future__ import annotations

import pytest

from ops_documents_client.testing import FakeDocumentsService, FakeType
from ops_identity import ServiceUnreachable

pytestmark = pytest.mark.asyncio


async def test_document_types_reads_every_page() -> None:
    types: list[FakeType] = [
        {"id": f"type_{n}", "name": f"Type {n}", "description": None, "latestVersion": 1} for n in range(3)
    ]
    fake = FakeDocumentsService(types=types, type_page_size=2)
    found = await fake.client().document_types("t_1", "team_ops")
    assert [t["id"] for t in found] == ["type_0", "type_1", "type_2"], found


async def test_a_503_reads_as_unreachable_so_the_caller_waits() -> None:
    fake = FakeDocumentsService(refuse=(503, "policy_unread", "The team's page picture policy could not be read."))
    with pytest.raises(ServiceUnreachable):
        await fake.client().reading("t_1", "team_ops", "fil_1", ocr="auto")
