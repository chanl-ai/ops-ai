"""Files a person attaches to a chat message, as a turn reads them: each page of the file's reading (documents-service,
with OCR on auto, so a scan is read), whole and in order, within the turn's share of attached text. The pages go to the
model in the attachments block and are cited like knowledge. The file itself is files-service's; the reading is
documents-service's (api/chat_attachments.py calls both)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from ops_agent_kernel.types import ATTACHMENT_KB, Passage

# The attached text one turn may read, across every file in the thread; a file past it says so in the reply.
TURN_TEXT_CHARS = 24_000

__all__ = ["ATTACHMENT_KB", "TURN_TEXT_CHARS", "Page", "pages_of", "passages"]


@dataclass(frozen=True)
class Page:
    page: int | None
    text: str


def pages_of(reading: dict[str, Any]) -> list[Page]:
    """A finished reading's pages that hold text, each whole."""
    out: list[Page] = []
    for p in cast(list[dict[str, Any]], reading.get("pages") or []):
        text = str(p.get("text") or "")
        if text.strip():
            out.append(Page(cast(int | None, p.get("number")), text))
    return out


def passages(name: str, file_id: str, pages: list[Page], budget: int) -> tuple[list[Passage], bool]:
    """An attachment's pages as passages a turn can cite, whole, until this turn's share of text runs out; the page
    that passes the share is cut to fit. True when some text was left out."""
    out: list[Passage] = []
    for p in pages:
        if budget <= 0:
            return out, True
        text = p.text if len(p.text) <= budget else p.text[:budget]
        budget -= len(text)
        out.append(Passage(file_id, name, name, "attached", text, ATTACHMENT_KB, p.page))
        if len(text) < len(p.text):
            return out, True
    return out, False
