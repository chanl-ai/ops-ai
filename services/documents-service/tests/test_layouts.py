"""Layouts (c-247), by failure mode: another team's or an unscanned file read into a layout (F1); a layout read again
for every caller, or an old one served after the layout engine changed (F2); a layout read with OCR confused with one
read without it (F2)."""

from __future__ import annotations

from typing import Any

import pytest

from ops_documents import layouts

from .conftest import OPS, Make
from .test_extractions import NOTICE, Floor, Models


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each layout actually read from bytes, by file name."""
    seen: list[str] = []
    real = layouts.build_layout

    def counted(data: bytes, **kw: Any) -> Any:
        seen.append(str(kw["filename"]))
        return real(data, **kw)

    monkeypatch.setattr(layouts, "build_layout", counted)
    return seen


async def test_a_layout_is_read_once_and_again_after_the_engine_changes(
    make: Make, builds: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    s = make(Models(), Floor())
    async with s.client as c:
        fid = await s.stored(NOTICE)
        before = await c.get(f"/v1/documents/layout/{fid}", headers=OPS)
        first = (await c.post("/v1/documents/layout", json={"fileId": fid}, headers=OPS)).json()["data"]
        again = await c.post("/v1/documents/layout", json={"fileId": fid}, headers=OPS)
        page = (await c.get(f"/v1/documents/layout/{fid}", params={"page": 1}, headers=OPS)).json()["data"]
        with_ocr = await c.post("/v1/documents/layout", json={"fileId": fid, "ocr": True}, headers=OPS)
        monkeypatch.setattr(layouts, "ENGINE", "layout-test")
        changed = await c.post("/v1/documents/layout", json={"fileId": fid}, headers=OPS)
    assert before.status_code == 404, before.text
    assert again.json()["data"] == first and page["blocks"] == first["blocks"], page
    assert with_ocr.status_code == 200 and changed.status_code == 200
    assert builds == ["notice.txt", "notice.txt", "notice.txt"], (
        "read once, then once with OCR, then for the new engine"
    )
    assert first["blocks"][0]["text"].startswith("Invoice INV-2207"), first["blocks"]


async def test_another_teams_or_an_unscanned_file_has_no_layout(make: Make, builds: list[str]) -> None:
    s = make(Models(), Floor())
    async with s.client as c:
        theirs = await s.stored(NOTICE, team="team_cards")
        pending = await s.stored(NOTICE + b"\n", clean=False)
        other = await c.post("/v1/documents/layout", json={"fileId": theirs}, headers=OPS)
        unscanned = await c.post("/v1/documents/layout", json={"fileId": pending}, headers=OPS)
    assert other.status_code == 404 and unscanned.status_code in (409, 423), (other.text, unscanned.text)
    assert builds == []
