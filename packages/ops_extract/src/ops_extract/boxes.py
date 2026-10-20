# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Where on the page each extracted field came from (c-252): the cited quote's words found in the file's layout,
narrowed to the value's words when the value sits inside the quote, as one box per line and the ids of the layout
blocks (or table cells) those words are in.

A field gets boxes only when its quote is found on the page it cites, the rule its confidence already follows, so a
box never points at text the model made up. Boxes are `{page, x, y, w, h}`, fractions of the page from the top left."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

from ops_extract.checks import fold

Layout = dict[str, Any]
# Words whose tops differ by less than this share of a word's height are on one line, so they share a box.
SAME_LINE = 0.5
# A table row the page text joins with " | " puts a separator in the quote that is not a word on the page.
SEPARATORS = {"|"}


def tokens(text: str) -> list[str]:
    """Folded words of `text`, without the row separators page text adds, as they are matched against layout words."""
    return [t for t in fold(text).split() if t not in SEPARATORS]


def _matches(page_word: str, token: str, *, first: bool, last: bool) -> bool:
    """A quote can start inside a page word ("No.SYN-1" quoted as "SYN-1") or end inside one ("0101," as "0101")."""
    if page_word == token:
        return True
    return (first and page_word.endswith(token)) or (last and page_word.startswith(token))


def runs(words: list[dict[str, Any]], wanted: list[str]) -> Iterator[list[dict[str, Any]]]:
    """Every run of `words`, in reading order, whose folded text is `wanted`."""
    folded = [fold(str(w["text"])) for w in words]
    n = len(wanted)
    for start in range(len(words) - n + 1):
        if all(_matches(folded[start + i], t, first=i == 0, last=i == n - 1) for i, t in enumerate(wanted)):
            yield words[start : start + n]


def _find(words: list[dict[str, Any]], wanted: list[str]) -> list[dict[str, Any]] | None:
    """The first run of `words`, in reading order, whose folded text is `wanted`."""
    return next(runs(words, wanted), None)


def union(words: list[dict[str, Any]]) -> list[float]:
    """The box around `words`, as [x0, top, x1, bottom] fractions of the page."""
    boxes = [cast(list[float], w["box"]) for w in words]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def line_boxes(words: list[dict[str, Any]], page: int) -> list[dict[str, Any]]:
    lines: list[list[list[float]]] = []
    for w in words:
        box = cast(list[float], w["box"])
        last = lines[-1][-1] if lines else None
        if last is not None and abs(box[1] - last[1]) < SAME_LINE * max(box[3] - box[1], 1e-6):
            lines[-1].append(box)
        else:
            lines.append([box])
    out: list[dict[str, Any]] = []
    for boxes in lines:
        x0, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
        out.append(
            {"page": page, "x": round(x0, 4), "y": round(top, 4), "w": round(x1 - x0, 4), "h": round(bottom - top, 4)}
        )
    return out


def _inside(box: list[float] | None, x: float, y: float) -> bool:
    return box is not None and box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _block_ids(layout: Layout, words: list[dict[str, Any]], page: int) -> list[str]:
    """The block, or the table cell when the word is in one, holding each word's centre; each id once, in order."""
    ids: list[str] = []
    blocks = [b for b in cast(list[dict[str, Any]], layout.get("blocks") or []) if int(b["page"]) == page]
    for w in words:
        box = cast(list[float], w["box"])
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        for b in blocks:
            if not _inside(b.get("box"), cx, cy):
                continue
            cells = cast(list[dict[str, Any]], b.get("cells") or [])
            cell = next((c for c in cells if _inside(c.get("box"), cx, cy)), None)
            found = str(cell["id"] if cell else b["id"])
            if found not in ids:
                ids.append(found)
            break
    return ids


def locate(layout: Layout, page: int | None, quote: str | None, value: Any) -> dict[str, Any] | None:
    """The field's `{boxes, blocks}`, or None when the quote is not on its page or the page has no word boxes."""
    if page is None or not quote:
        return None
    on_page = [
        w for w in cast(list[dict[str, Any]], layout.get("words") or []) if int(w["page"]) == page and w.get("box")
    ]
    quoted = tokens(quote)
    run = _find(on_page, quoted) if quoted else None
    if run is None:
        return None
    wanted = tokens(str(value)) if value is not None else []
    narrowed = _find(run, wanted) if wanted and len(wanted) < len(run) else None
    chosen = narrowed or run
    return {"boxes": line_boxes(chosen, page), "blocks": _block_ids(layout, chosen, page)}


def printed(result: dict[str, Any]) -> Any:
    """The text a field's value was printed as, which its box is narrowed to: the cleaned value when it is in the
    quote (a number without its label), else what the model said. A normalised value (a date as 2026-10-02, an amount
    as 1250.0) is not printed anywhere, so it is never used."""
    value, said = result.get("value"), result.get("extractedValue")
    quote = str(cast(dict[str, Any], result.get("citation") or {}).get("quote") or "")
    if isinstance(value, str) and value and " ".join(tokens(value)) in " ".join(tokens(quote)):
        return value
    return said


def with_boxes(out: dict[str, Any], layout: Layout) -> dict[str, Any]:
    """The scored answer with `boxes` and `blocks` on every field whose quote was found, single or several records."""

    def place(fields: dict[str, dict[str, Any]]) -> None:
        for result in fields.values():
            citation = cast(dict[str, Any], result.get("citation") or {})
            found = locate(layout, citation.get("page"), citation.get("quote"), printed(result))
            if found is not None:
                result.update(found)

    if "records" in out:
        for record in cast(list[dict[str, Any]], out["records"]):
            place(cast(dict[str, dict[str, Any]], record["fields"]))
    else:
        place(cast(dict[str, dict[str, Any]], out.get("fields") or {}))
    return out
