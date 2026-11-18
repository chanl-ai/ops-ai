# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Where on the page each extracted field came from: the cited quote's words found in the file's layout,
narrowed to the value's words when the value sits inside the quote, as one box per line and the ids of the layout
blocks (or table cells) those words are in.

A field gets boxes only when its quote is found on the page it cites, the rule its confidence already follows, so a
box never points at text the model made up. Boxes are `{page, x, y, w, h}`, fractions of the page from the top left."""

from __future__ import annotations

from collections.abc import Iterator

from ops_extract.checks import entries, fold
from ops_extract.shapes import Box, Layout, LayoutWord, Located, Rect
from ops_service_kit.http import Json, JsonValue
from ops_service_kit.narrow import Malformed, an_object

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


def runs(words: list[LayoutWord], wanted: list[str]) -> Iterator[list[LayoutWord]]:
    """Every run of `words`, in reading order, whose folded text is `wanted`."""
    folded = [fold(w["text"]) for w in words]
    n = len(wanted)
    for start in range(len(words) - n + 1):
        if all(_matches(folded[start + i], t, first=i == 0, last=i == n - 1) for i, t in enumerate(wanted)):
            yield words[start : start + n]


def _find(words: list[LayoutWord], wanted: list[str]) -> list[LayoutWord] | None:
    """The first run of `words`, in reading order, whose folded text is `wanted`."""
    return next(runs(words, wanted), None)


def union(words: list[LayoutWord]) -> Rect:
    """The box around `words`, as [x0, top, x1, bottom] fractions of the page."""
    boxes = [w["box"] for w in words]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def line_boxes(words: list[LayoutWord], page: int) -> list[Box]:
    lines: list[list[Rect]] = []
    for w in words:
        box = w["box"]
        last = lines[-1][-1] if lines else None
        if last is not None and abs(box[1] - last[1]) < SAME_LINE * max(box[3] - box[1], 1e-6):
            lines[-1].append(box)
        else:
            lines.append([box])
    out: list[Box] = []
    for boxes in lines:
        x0, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
        out.append(
            {"page": page, "x": round(x0, 4), "y": round(top, 4), "w": round(x1 - x0, 4), "h": round(bottom - top, 4)}
        )
    return out


def _inside(box: Rect | None, x: float, y: float) -> bool:
    return box is not None and box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _block_ids(layout: Layout, words: list[LayoutWord], page: int) -> list[str]:
    """The block, or the table cell when the word is in one, holding each word's centre; each id once, in order."""
    ids: list[str] = []
    blocks = [b for b in layout.get("blocks") or [] if b["page"] == page]
    for w in words:
        box = w["box"]
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        for b in blocks:
            if not _inside(b.get("box"), cx, cy):
                continue
            cell = next((c for c in b.get("cells") or [] if _inside(c.get("box"), cx, cy)), None)
            found = cell["id"] if cell else b["id"]
            if found not in ids:
                ids.append(found)
            break
    return ids


def locate(layout: Layout, page: JsonValue, quote: JsonValue, value: JsonValue) -> Located | None:
    """The field's `{boxes, blocks}`, or None when the quote is not on its page or the page has no word boxes. The
    page and quote are a citation's as stored: a page that is no page number matches no words."""
    if page is None or not quote:
        return None
    if not isinstance(quote, str):
        raise Malformed(f"quote {quote!r} is not text")
    on_page = [w for w in layout.get("words") or [] if w["page"] == page and w.get("box")]
    quoted = tokens(quote)
    run = _find(on_page, quoted) if quoted else None
    if run is None:
        return None
    number = run[0]["page"]
    wanted = tokens(str(value)) if value is not None else []
    narrowed = _find(run, wanted) if wanted and len(wanted) < len(run) else None
    chosen = narrowed or run
    return {"boxes": line_boxes(chosen, number), "blocks": _block_ids(layout, chosen, number)}


def printed(result: Json) -> JsonValue:
    """The text a field's value was printed as, which its box is narrowed to: the cleaned value when it is in the
    quote (a number without its label), else what the model said. A normalised value (a date as 2026-10-02, an amount
    as 1250.0) is not printed anywhere, so it is never used."""
    value, said = result.get("value"), result.get("extractedValue")
    quote = str(an_object(result.get("citation") or {}, "citation").get("quote") or "")
    if isinstance(value, str) and value and " ".join(tokens(value)) in " ".join(tokens(quote)):
        return value
    return said


def box_json(box: Box) -> Json:
    """A box as the JSON a field's result stores."""
    return {"page": box["page"], "x": box["x"], "y": box["y"], "w": box["w"], "h": box["h"]}


def with_boxes(out: Json, layout: Layout) -> Json:
    """The scored answer with `boxes` and `blocks` on every field whose quote was found, single or several records."""

    def place(fields: Json) -> None:
        for key, value in fields.items():
            result = an_object(value, f"field {key}")
            citation = an_object(result.get("citation") or {}, f"field {key}'s citation")
            found = locate(layout, citation.get("page"), citation.get("quote"), printed(result))
            if found is not None:
                result["boxes"] = [box_json(b) for b in found["boxes"]]
                result["blocks"] = [*found["blocks"]]

    if "records" in out:
        for record in entries(out["records"]):
            place(an_object(an_object(record, "a record")["fields"], "a record's fields"))
    else:
        place(an_object(out.get("fields") or {}, "fields"))
    return out


def _number(b: Json, key: str) -> float:
    value = b[key]
    if not isinstance(value, int | float | str):
        raise Malformed(f"box {key} {value!r} is not a number")
    return float(value)


def boxes_of(value: JsonValue) -> list[Box]:
    """A field result's stored `boxes` read back; a box missing a part, or with a part that is no number, raises."""
    out: list[Box] = []
    for item in entries(value):
        b = an_object(item, "a box")
        page = b["page"]
        if not isinstance(page, int | float | str):
            raise Malformed(f"box page {page!r} is not a number")
        out.append(
            {"page": int(page), "x": _number(b, "x"), "y": _number(b, "y"), "w": _number(b, "w"), "h": _number(b, "h")}
        )
    return out
