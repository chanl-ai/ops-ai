"""Files a person attaches to a chat message, as a turn reads them: each page's text, from documents-service's
full-text read, cut into passages a turn cites like knowledge, within the turn's share of text. The file itself is
files-service's; the read is documents-service's (api/chat_attachments.py calls both)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from ops_agent_kernel.ports import KnowledgePort
from ops_agent_kernel.types import Passage

# The attached text one turn may read, across every file in the thread; a file past it says so in the reply.
TURN_TEXT_CHARS = 24_000
# A page longer than this is cited in pieces, so one long page does not take the whole share.
CHUNK_CHARS = 2_000


@dataclass(frozen=True)
class Page:
    page: int | None
    section: str
    text: str


def pages_of(read: dict[str, Any]) -> list[Page]:
    """A full-text read's pages ({number, text}) as page-numbered pieces of at most `CHUNK_CHARS`, split on lines."""
    out: list[Page] = []
    for p in cast(list[dict[str, Any]], read.get("pages") or []):
        number, piece = cast(int | None, p.get("number")), ""
        for line in str(p.get("text") or "").splitlines():
            if piece and len(piece) + len(line) + 1 > CHUNK_CHARS:
                out.append(Page(number, "", piece))
                piece = ""
            piece = f"{piece}\n{line}" if piece else line
        if piece.strip():
            out.append(Page(number, "", piece))
    return out


def passages(name: str, file_id: str, pages: list[Page], budget: int) -> tuple[list[Passage], bool]:
    """An attachment's pages as passages a turn can cite, within this turn's share of text; True when some were cut."""
    out: list[Passage] = []
    for p in pages:
        if budget - len(p.text) < 0:
            return out, True
        budget -= len(p.text)
        out.append(Passage(file_id, name, p.section or name, "attached", p.text, "attachment", p.page))
    return out, False


@dataclass
class WithAttachments:
    """The turn's knowledge: the attached files' passages first, then whatever the knowledge bases find. Attached
    files are what the person asked about, so they are never crowded out by the bases."""

    inner: KnowledgePort
    attached: list[Passage]

    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Passage]:
        words = {w for w in query.lower().split() if len(w) > 3}
        ranked = sorted(self.attached, key=lambda p: -sum(w in p.text.lower() for w in words))
        bases = [i for i in kb_ids if i != "attachment"]
        found = await self.inner.search(query, bases, k=k) if bases else []
        return [*ranked[:k], *found]
