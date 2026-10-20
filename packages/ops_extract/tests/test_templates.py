"""Layout templates (c-253), by failure mode: a file printed from the known form not matched, or read from the wrong
words; a form shifted a little missing, or a tolerance that lets anything match; another layout matched; a required
anchor missing and the page matched anyway. Forms are printed here from one master with reportlab."""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas

from ops_extract.boxes import locate, runs, tokens, union
from ops_extract.layout import build_layout
from ops_extract.templates import Match, Miss, Read, fingerprint, match, read, suggest

LABELS = [("Case No.", "case_no"), ("Debtor", "debtor"), ("Amount due", "amount"), ("Served on", "served")]
MASTER = {"case_no": "SYN-2026-0101", "debtor": "Morgan Example", "amount": "$1,250.00", "served": "03/04/2026"}
OTHER = {"case_no": "SYN-2026-0202", "debtor": "Quinn Caption", "amount": "$980.10", "served": "05/06/2026"}


def form(values: dict[str, str], *, dx: float = 0, dy: float = 0, labels: list[tuple[str, str]] = LABELS) -> bytes:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72 + dx, LETTER[1] - 60 - dy, "RESTRAINING NOTICE")
    c.setFont("Helvetica", 11)
    for i, (label, key) in enumerate(labels):
        y = LETTER[1] - 120 - 30 * i - dy
        c.drawString(72 + dx, y, label)
        c.drawString(220 + dx, y, values[key])
    c.save()
    return buf.getvalue()


def template_from(layout: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    """Anchors at the master's labels, zones around its values with a margin, as c-254 will infer them."""
    words = [w for w in layout["words"] if w["page"] == 1]
    anchors: list[dict[str, Any]] = []
    zones: list[dict[str, Any]] = []
    for label, key in LABELS:
        anchors.append({"text": label, "box": union(next(runs(words, tokens(label))))})
        x0, top, x1, bottom = union(next(runs(words, tokens(values[key]))))
        zones.append({"field": key, "box": [x0 - 0.01, top - 0.005, x1 + 0.15, bottom + 0.005]})
    return {"id": "tpl_notice", "pages": [{"page": 1, "anchors": anchors, "zones": zones}]}


TEMPLATE = template_from(build_layout(form(MASTER), filename="m.pdf"), MASTER)


def values(answers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {k: a["value"] for k, a in answers.items()}


def test_a_file_printed_from_the_form_matches_and_reads_each_zone() -> None:
    layout = build_layout(form(OTHER), filename="o.pdf")
    found = match(TEMPLATE, layout)
    assert isinstance(found, Match) and found.pages[1][0] == 1, found
    answers = read(TEMPLATE, found, layout)
    assert values(answers) == OTHER and answers["case_no"]["page"] == 1, answers


def test_a_form_shifted_a_little_still_reads_and_no_tolerance_misses_it() -> None:
    shifted = build_layout(form(OTHER, dx=9, dy=7), filename="s.pdf")
    found = match(TEMPLATE, shifted)
    assert isinstance(found, Match), found
    assert values(read(TEMPLATE, found, shifted)) == OTHER
    assert isinstance(match(TEMPLATE, shifted, tolerance=0.0), Miss)


def test_another_layout_misses_with_the_anchors_it_lacked() -> None:
    other = [("Index number", "case_no"), ("Judgment debtor", "debtor"), ("Amount due", "amount"), ("Date", "served")]
    found = match(TEMPLATE, build_layout(form(OTHER, labels=other), filename="x.pdf"))
    assert isinstance(found, Miss) and "Case No." in found.missing and found.score < 0.8, found


def test_a_required_anchor_missing_misses_even_when_the_share_is_reached() -> None:
    """Five anchors, four found (0.8, the share), but the one missing is required."""
    template = {
        **TEMPLATE,
        "pages": [
            {
                **TEMPLATE["pages"][0],
                "anchors": [*TEMPLATE["pages"][0]["anchors"], {"text": "Index", "box": [0.1, 0.5, 0.2, 0.52]}],
            }
        ],
    }
    optional = {
        **template,
        "pages": [
            {
                **template["pages"][0],
                "anchors": [
                    *TEMPLATE["pages"][0]["anchors"],
                    {"text": "Index", "box": [0.1, 0.5, 0.2, 0.52], "required": False},
                ],
            }
        ],
    }
    layout = build_layout(form(OTHER), filename="o.pdf")
    assert isinstance(match(template, layout), Miss) and isinstance(match(optional, layout), Match)


def read_of(pdf: bytes, vals: dict[str, str]) -> Read:
    """A finished read: the layout and each field's boxes, located from its value as c-252 locates them."""
    layout = build_layout(pdf, filename="r.pdf")
    boxes: dict[str, list[dict[str, Any]]] = {}
    for key, value in vals.items():
        found = locate(layout, 1, value, value)
        boxes[key] = found["boxes"] if found else []
    return Read(layout, boxes)


def test_a_suggestion_from_one_read_reads_another_printing_of_the_form() -> None:
    """c-254 F1, F2: anchors are the labels, never a value, so the draft matches a file with other values."""
    draft = suggest([read_of(form(MASTER), MASTER)], template_id="tpl_s")
    anchors = [a["text"] for a in draft["pages"][0]["anchors"]]
    assert anchors == [label for label, _ in LABELS], anchors
    other = build_layout(form(OTHER), filename="o.pdf")
    found = match(draft, other)
    assert isinstance(found, Match) and values(read(draft, found, other)) == OTHER, found


def test_an_anchor_one_printing_moves_is_dropped_and_the_rest_kept() -> None:
    moved = [("Case No.", "case_no"), ("Debtor", "debtor"), ("Amount due", "amount"), ("Date of service", "served")]
    draft = suggest([read_of(form(MASTER), MASTER), read_of(form(OTHER, labels=moved), OTHER)], template_id="tpl_s")
    assert [a["text"] for a in draft["pages"][0]["anchors"]] == ["Case No.", "Debtor", "Amount due"], draft


def test_printings_of_one_master_share_a_fingerprint_and_another_layout_does_not() -> None:
    other_layout = [
        ("Index number", "case_no"),
        ("Debtor", "debtor"),
        ("Amount due", "amount"),
        ("Served on", "served"),
    ]
    one, two = fingerprint(read_of(form(MASTER), MASTER)), fingerprint(read_of(form(OTHER), OTHER))
    assert one == two != fingerprint(read_of(form(OTHER, labels=other_layout), OTHER))


def test_a_suggested_zone_stops_before_the_next_label_on_its_line() -> None:
    """Two label and value pairs on one line: the first value's zone never reads the second label."""

    def two_columns(holder: str, balance: str) -> bytes:
        buf = io.BytesIO()
        c = Canvas(buf, pagesize=LETTER)
        c.setFont("Helvetica", 10)
        c.drawString(72, 650, "Account holder")
        c.drawString(180, 650, holder)
        c.drawString(290, 650, "Opening balance")
        c.drawString(420, 650, balance)
        c.save()
        return buf.getvalue()

    first = {"holder": "Avery Specimen", "balance": "$88.12"}
    draft = suggest([read_of(two_columns(**first), first)], template_id="tpl_two")
    other = build_layout(two_columns("Quinn Caption", "$12,004.00"), filename="t.pdf")
    found = match(draft, other)
    assert isinstance(found, Match), draft
    assert values(read(draft, found, other)) == {"holder": "Quinn Caption", "balance": "$12,004.00"}
