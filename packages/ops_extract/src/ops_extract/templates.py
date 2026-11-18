# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Layout templates: a known form read from its zones with no model call.

A template sits on a document type version and lists, per template page, anchor labels with the box each is printed
in and one zone per field, all as [x0, top, x1, bottom] fractions of the page, the layout's own boxes. A file page
matches a template page when every required anchor is found within ANCHOR_TOLERANCE of its box and the share found
reaches MATCH_SHARE. The found anchors' mean offset moves every zone, so a scan shifted by a few millimetres still
reads; rotation and scale are not corrected, so a skewed scan misses, which sends it to the model.

A zone's answer is the layout words inside it, given as both value and quote, so the field checks score it as they
score a model's answer: cleanup rules, pattern, type, and on a scan the words' recognition confidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ops_extract.boxes import runs, tokens, union
from ops_extract.shapes import (
    Box,
    Layout,
    LayoutWord,
    Rect,
    SavedAnchor,
    SavedTemplate,
    SavedTemplatePage,
    Template,
    TemplateAnchor,
    TemplatePage,
)
from ops_service_kit.http import Json, JsonValue
from ops_service_kit.narrow import Malformed, a_list, an_object, entries, json_object

# How far a found anchor may sit from the box the template expects, as a fraction of the page, and the share of a
# page's anchors that must be found besides every required one.
ANCHOR_TOLERANCE = 0.03
MATCH_SHARE = 0.8
# Words on one line differ in top by less than this share of their height.
SAME_LINE = 0.5
# Set on a template carried to a version that lacks a field it reads: kept for a person to rebuild, never matched.
NEEDS_REBUILD = "needsRebuild"


@dataclass(frozen=True)
class Match:
    """Which file page each template page matched, with the offset its anchors were found at."""

    template_id: str
    # template page -> (file page, dx, dy)
    pages: dict[int, tuple[int, float, float]]


@dataclass(frozen=True)
class Miss:
    """The best a template did against the file: the share of its anchors found and the ones missing."""

    template_id: str
    score: float
    missing: list[str] = field(default_factory=list[str])

    def wire(self) -> Json:
        return {"templateId": self.template_id, "score": round(self.score, 3), "missingAnchors": [*self.missing]}


def _words(layout: Layout, page: int) -> list[LayoutWord]:
    return [w for w in layout.get("words") or [] if w["page"] == page and w.get("box")]


def _box(w: LayoutWord) -> Rect:
    return w["box"]


def _rect(value: JsonValue) -> Rect:
    """A saved zone's box, [x0, top, x1, bottom]; `problems` refused any other when the version was saved."""
    rect: Rect = []
    for v in a_list(value, "box"):
        if not isinstance(v, int | float):
            raise Malformed(f"box holds {v!r}, not a number")
        rect.append(float(v))
    return rect


def _zones(tpage: SavedTemplatePage | TemplatePage) -> list[Json]:
    """A page's zones as saved: any empty value is none, as `problems` reads it."""
    zones = tpage.get("zones")
    held = zones if isinstance(zones, list) else entries(zones)
    return [an_object(z, "a zone") for z in held]


def _page_no(tpage: SavedTemplatePage | TemplatePage) -> int:
    return tpage.get("page") or 1


def _near(found: Rect, expected: Rect, tolerance: float) -> bool:
    return abs(found[0] - expected[0]) <= tolerance and abs(found[1] - expected[1]) <= tolerance


def _anchor(words: list[LayoutWord], anchor: SavedAnchor | TemplateAnchor, tolerance: float) -> Rect | None:
    """The box of the anchor's words closest to where the template expects it, within the tolerance."""
    expected = anchor["box"]
    near = [
        b for b in (union(run) for run in runs(words, tokens(str(anchor["text"])))) if _near(b, expected, tolerance)
    ]
    return min(near, key=lambda b: abs(b[0] - expected[0]) + abs(b[1] - expected[1])) if near else None


@dataclass(frozen=True)
class _PageScore:
    matched: bool
    share: float
    dx: float
    dy: float
    missing: list[str]


def _page_score(words: list[LayoutWord], tpage: SavedTemplatePage | TemplatePage, tolerance: float) -> _PageScore:
    anchors = tpage["anchors"]
    found: list[tuple[Rect, Rect]] = []
    missing: list[str] = []
    required_missing = False
    for a in anchors:
        box = _anchor(words, a, tolerance)
        if box is None:
            missing.append(str(a["text"]))
            required_missing = required_missing or a.get("required", True) is not False
        else:
            found.append((box, a["box"]))
    share = len(found) / len(anchors) if anchors else 0.0
    dx = sum(f[0] - e[0] for f, e in found) / len(found) if found else 0.0
    dy = sum(f[1] - e[1] for f, e in found) / len(found) if found else 0.0
    return _PageScore(bool(found) and not required_missing and share >= MATCH_SHARE, share, dx, dy, missing)


def match(template: SavedTemplate | Template, layout: Layout, *, tolerance: float = ANCHOR_TOLERANCE) -> Match | Miss:
    """The file pages the template's pages are printed on, each file page used once, or the best it managed on the
    first template page it could not place."""
    numbers = sorted({p["number"] for p in layout.get("pages") or []})
    tid = template["id"]
    taken: dict[int, tuple[int, float, float]] = {}
    for tpage in template["pages"]:
        best = _PageScore(False, 0.0, 0.0, 0.0, [str(a["text"]) for a in tpage["anchors"]])
        used = {t[0] for t in taken.values()}
        for n in numbers:
            if n in used:
                continue
            score = _page_score(_words(layout, n), tpage, tolerance)
            if score.matched:
                best = score
                taken[_page_no(tpage)] = (n, score.dx, score.dy)
                break
            if score.share > best.share:
                best = score
        if not best.matched:
            return Miss(tid, best.share, best.missing)
    return Match(tid, taken) if taken else Miss(tid, 0.0, [])


def _reading(words: list[LayoutWord]) -> str:
    """Words in reading order: a space between words on a line, a line break between lines."""
    lines: list[list[LayoutWord]] = []
    for w in sorted(words, key=lambda w: (_box(w)[1], _box(w)[0])):
        last = _box(lines[-1][0]) if lines else None
        box = _box(w)
        if last is not None and abs(box[1] - last[1]) < SAME_LINE * max(box[3] - box[1], 1e-6):
            lines[-1].append(w)
        else:
            lines.append([w])
    return "\n".join(" ".join(w["text"] for w in sorted(line, key=lambda w: _box(w)[0])) for line in lines)


def read(template: SavedTemplate | Template, found: Match, layout: Layout) -> Json:
    """Each zone's answer, keyed by field, in the shape the field checks score: {value, quote, page}. A zone with no
    words answers no value."""
    answers: Json = {}
    for tpage in template["pages"]:
        page, dx, dy = found.pages[_page_no(tpage)]
        words = _words(layout, page)
        for zone in _zones(tpage):
            x0, top, x1, bottom = _rect(zone["box"])
            inside = [
                w
                for w in words
                if x0 + dx <= (_box(w)[0] + _box(w)[2]) / 2 <= x1 + dx
                and top + dy <= (_box(w)[1] + _box(w)[3]) / 2 <= bottom + dy
            ]
            text = _reading(inside) if inside else None
            answers[str(zone["field"])] = {"value": text, "quote": text, "page": page if text else None}
    return answers


def _bad_box(box: JsonValue) -> bool:
    if not isinstance(box, list) or len(box) != 4:
        return True
    b = [v for v in box if isinstance(v, int | float) and not isinstance(v, bool)]
    if len(b) != 4 or not all(0 <= v <= 1 for v in b):
        return True
    return not (b[0] < b[2] and b[1] < b[3])


def problems(templates: JsonValue, keys: set[str]) -> list[str]:
    """What is wrong with a version's templates, checked when the version is saved: each has an id, pages numbered
    from 1, anchors with text, zones naming the version's own fields, and boxes inside the page."""
    if not isinstance(templates, list):
        return ["templates is a list"]
    found: list[str] = []
    ids: set[str] = set()
    for t in templates:
        tpl = json_object(t)
        tid = tpl.get("id")
        if not isinstance(t, dict) or not isinstance(tid, str) or not tid:
            found.append("every template has an id")
            continue
        if tid in ids:
            found.append(f"template {tid} is named twice")
        ids.add(tid)
        pages = tpl.get("pages")
        if not isinstance(pages, list) or not pages:
            found.append(f"template {tid}: pages is a list of at least one page")
            continue
        for p in pages:
            page = json_object(p)
            n = page.get("page", 1)
            if not isinstance(n, int) or isinstance(n, bool) or n < 1:
                found.append(f"template {tid}: a page is numbered from 1")
            anchors = entries(page.get("anchors"))
            if not anchors:
                found.append(f"template {tid} page {n}: at least one anchor")
            for a in anchors:
                anchor = json_object(a)
                if not isinstance(a, dict) or not str(anchor.get("text") or "").strip():
                    found.append(f"template {tid} page {n}: every anchor has text")
                elif _bad_box(anchor.get("box")):
                    found.append(f"template {tid} page {n}: anchor {anchor['text']!r} has a box outside the page")
            for z in entries(page.get("zones")):
                zone = json_object(z)
                if zone.get("field") not in keys and not tpl.get(NEEDS_REBUILD):
                    named = zone.get("field")
                    found.append(f"template {tid} page {n}: zone names {named!r}, not a field of the version")
                elif _bad_box(zone.get("box")):
                    found.append(f"template {tid} page {n}: zone {zone['field']} has a box outside the page")
    return found


# ── Suggestions ──

# A suggested zone is widened by this much past its value on the right (a longer value on the next file) and by
# ZONE_MARGIN around it. An anchor is at most LABEL_WORDS words: the nearest word left of the value on its line within
# LABEL_REACH (a form's label column), then the words before it while each gap is under LABEL_GAP; else the line just
# above within LABEL_ABOVE.
ZONE_MARGIN = 0.006
ZONE_GROWTH = 0.1
LABEL_WORDS = 6
LABEL_GAP = 0.03
LABEL_REACH = 0.35
LABEL_ABOVE = 0.04
# Positions are rounded to this step in a layout fingerprint, so files printed from one master share one.
FINGERPRINT_STEP = 0.02


@dataclass(frozen=True)
class Read:
    """A finished read of a file: its layout, and each field's boxes where its value was found."""

    layout: Layout
    boxes: dict[str, list[Box]]


def _centre_in(w: LayoutWord, box: Rect) -> bool:
    cx, cy = (_box(w)[0] + _box(w)[2]) / 2, (_box(w)[1] + _box(w)[3]) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def _frac(b: Box) -> Rect:
    return [float(b["x"]), float(b["y"]), float(b["x"]) + float(b["w"]), float(b["y"]) + float(b["h"])]


def _value_words(read: Read, page: int) -> list[LayoutWord]:
    """The page's words inside any field's value boxes, which can never be a label."""
    value_boxes = [_frac(b) for bs in read.boxes.values() for b in bs if b["page"] == page]
    return [w for w in _words(read.layout, page) if any(_centre_in(w, vb) for vb in value_boxes)]


def _label(words: list[LayoutWord], values: list[LayoutWord], vbox: Rect) -> list[LayoutWord]:
    """The label words nearest a value: the run just left of it on its line, else the nearest line above it."""
    others = [w for w in words if w not in values]
    height = max(vbox[3] - vbox[1], 1e-6)
    left = sorted(
        (w for w in others if abs(_box(w)[1] - vbox[1]) < SAME_LINE * height and _box(w)[2] <= vbox[0] + 1e-6),
        key=lambda w: -_box(w)[2],
    )
    run: list[LayoutWord] = []
    edge = vbox[0]
    for w in left:
        if edge - _box(w)[2] > (LABEL_REACH if not run else LABEL_GAP) or len(run) >= LABEL_WORDS:
            break
        run.insert(0, w)
        edge = _box(w)[0]
    if run:
        return run
    above = [
        w
        for w in others
        if 0 <= vbox[1] - _box(w)[3] <= LABEL_ABOVE and _box(w)[0] < vbox[2] and _box(w)[2] > vbox[0] - LABEL_GAP
    ]
    if not above:
        return []
    nearest = max(_box(w)[3] for w in above)
    line = sorted((w for w in above if abs(_box(w)[3] - nearest) < SAME_LINE * height), key=lambda w: _box(w)[0])
    return line[:LABEL_WORDS]


def _one(read: Read) -> dict[int, TemplatePage]:
    """Per page, the anchors and zones one read suggests."""
    pages: dict[int, TemplatePage] = {}
    for key, bs in read.boxes.items():
        if not bs:
            continue
        page = bs[0]["page"]
        on_page = [_frac(b) for b in bs if b["page"] == page]
        vbox = [
            min(b[0] for b in on_page),
            min(b[1] for b in on_page),
            max(b[2] for b in on_page),
            max(b[3] for b in on_page),
        ]
        # A longer value on the next file may run right, but never into the next word printed on the line, which is
        # a label or another field: the zone stops short of it.
        words = _words(read.layout, page)
        values = _value_words(read, page)
        height = max(vbox[3] - vbox[1], 1e-6)
        right = [
            _box(w)[0]
            for w in words
            if w not in values and abs(_box(w)[1] - vbox[1]) < SAME_LINE * height and _box(w)[0] >= vbox[2] - 1e-6
        ]
        grow = max(ZONE_GROWTH, vbox[2] - vbox[0])
        x1 = min(vbox[2] + grow, min(right) - ZONE_MARGIN) if right else vbox[2] + grow
        zone = [
            max(0.0, vbox[0] - 0.01),
            max(0.0, vbox[1] - ZONE_MARGIN),
            min(1.0, max(x1, vbox[2])),
            min(1.0, vbox[3] + ZONE_MARGIN),
        ]
        entry = pages.setdefault(page, TemplatePage(page=page, anchors=[], zones=[]))
        entry["zones"].append({"field": key, "box": [round(v, 4) for v in zone]})
        label = _label(words, values, vbox)
        text = " ".join(w["text"] for w in label)
        if text and all(a["text"] != text for a in entry["anchors"]):
            entry["anchors"].append({"text": text, "box": [round(v, 4) for v in union(label)]})
    return pages


def suggest(reads: list[Read], *, template_id: str) -> Template:
    """A draft template from finished reads of one form. Zones cover every read's value; an anchor from the first read
    is kept only when every other read prints it within ANCHOR_TOLERANCE of the same place, so a header that changes
    between printings is not relied on. A page left with no anchor is dropped, since nothing could match it."""
    if not reads:
        return {"id": template_id, "pages": []}
    first = _one(reads[0])
    for other in reads[1:]:
        for n, page in _one(other).items():
            if n not in first:
                continue
            zones = {z["field"]: z for z in first[n]["zones"]}
            for z in page["zones"]:
                if z["field"] in zones:
                    a, b = zones[z["field"]]["box"], z["box"]
                    zones[z["field"]]["box"] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                else:
                    first[n]["zones"].append(z)
        for n, page in first.items():
            words = _words(other.layout, n)
            page["anchors"] = [a for a in page["anchors"] if _anchor(words, a, ANCHOR_TOLERANCE) is not None]
    return {"id": template_id, "pages": [p for _, p in sorted(first.items()) if p["anchors"] and p["zones"]]}


def fingerprint(read: Read) -> str:
    """The layout's printed form without its values: every word that is not inside a field's value box, with its
    position rounded to FINGERPRINT_STEP. Files printed from one master with different values share it."""
    parts: list[str] = []
    for page in sorted({p["number"] for p in read.layout.get("pages") or []}):
        values = _value_words(read, page)
        for w in _words(read.layout, page):
            if w in values:
                continue
            x, y = (round(_box(w)[i] / FINGERPRINT_STEP) for i in (0, 1))
            parts.append(f"{page}:{x}:{y}:{w['text'].casefold()}")
    return hashlib.sha256("\n".join(sorted(parts)).encode()).hexdigest()[:16]
