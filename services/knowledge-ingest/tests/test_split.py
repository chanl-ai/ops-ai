# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
from __future__ import annotations

import json
import re
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

import knowledge_ingest
from knowledge_ingest.models import IngestSettings, ParsedDocument, TableColumn
from knowledge_ingest.parsers import parse
from knowledge_ingest.split import PRESETS, InvalidIngestError, document_digest, split
from knowledge_ingest.testing import FakeModelClient
from knowledge_ingest.text import approx_tokens
from tests.conftest import fixture_bytes


def md(text: str) -> ParsedDocument:
    return parse(text.encode(), filename="doc.md")


def settings(**kw: Any) -> IngestSettings:
    return IngestSettings.model_validate(kw)


def sentences(n: int, start: int = 0) -> str:
    return " ".join(f"Clause {i} sets the fee for case {i} at {i} dollars." for i in range(start, start + n))


def test_no_chunk_exceeds_size_with_overlong_sentence() -> None:
    overlong = " ".join(f"word{i}" for i in range(120))  # one sentence, no full stop, ~240 tokens
    doc = md(f"# Policy\n\n{sentences(5)} {overlong}. {sentences(5, 5)}")
    result = split(doc, settings(strategies=["structure"], size=100, overlap=20))
    assert len(result.chunks) > 1
    assert max(approx_tokens(c.text) for c in result.chunks) <= 100


def test_fixed_windows_respect_size_and_overlap() -> None:
    words = [f"w{i:04d}" for i in range(600)]
    doc = md("# A\n\n" + " ".join(words[:300]) + "\n\n# B\n\n" + " ".join(words[300:]))
    result = split(doc, settings(strategies=["fixed"], size=100, overlap=20))
    texts = [c.text.split() for c in result.chunks]
    assert all(approx_tokens(" ".join(t)) <= 100 for t in texts)
    for a, b in pairwise(texts):
        shared = [w for w in a if w in set(b)]
        assert shared == b[: len(shared)], "the next window must start with the previous window's tail"
        assert 0 < approx_tokens(" ".join(shared)) <= 20
    assert texts[0][0] == "w0000"
    assert texts[-1][-1] == "w0599"


def test_context_header_once_per_chunk_with_overlap() -> None:
    doc = md(f"# Card policy\n\n## Fees\n\n{sentences(30)}")
    result = split(doc, settings(strategies=["structure", "context_headers"], size=100, overlap=40))
    assert len(result.chunks) > 2
    header = "Card policy > Fees"
    for chunk in result.chunks:
        assert chunk.indexed_text.startswith(header + "\n\n")
        assert chunk.indexed_text.count("Fees") == 1
        assert "Fees" not in chunk.text and "Card policy" not in chunk.text


def test_parent_child_returns_parent() -> None:
    body = sentences(12)
    doc = md(f"# Lending\n\n## Eligibility\n\n{body}")
    result = split(doc, settings(strategies=PRESETS["policy_manual"], size=400, overlap=0, child_size=40))
    [parent] = result.chunks
    assert parent.kind == "parent"
    assert parent.text == body
    units = result.index_units()
    assert {u.kind for u in units} == {"child"}
    assert len(units) > 1
    for unit in units:
        assert unit.chunk_index == parent.index
        assert unit.indexed_text.removeprefix("Lending > Eligibility\n\n") in parent.text


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"strategies": ["structure", "fixed"]}, "Choose one way to split"),
        ({"strategies": ["fixed", "parent_child"]}, "need sections"),
        ({"size": 50}, "between 100 and 2000"),
        ({"size": 200, "overlap": 200}, "smaller than the chunk size"),
        ({"strategies": ["structure", "parent_child"], "size": 200, "child_size": 200}, "Child chunks"),
        (
            {
                "strategies": ["table_rows"],
                "columns": [
                    {"name": "A", "role": "searchable", "key": True},
                    {"name": "B", "role": "searchable", "key": True},
                ],
            },
            "Only one column",
        ),
        ({"strategies": ["table_rows"], "columns": [{"name": "A", "role": "metadata", "key": True}]}, "searchable"),
        ({"strategies": ["structure", "faq"], "model": ""}, "model alias"),
    ],
)
def test_invalid_settings_refused(kw: dict[str, Any], message: str) -> None:
    with pytest.raises(InvalidIngestError, match=message) as err:
        split(md("text"), settings(**kw))
    assert err.value.code == "invalid_ingest"


def fee_columns() -> list[TableColumn]:
    return [
        TableColumn(name="Product", role="searchable", key=True),
        TableColumn(name="Monthly fee", role="metadata"),
        TableColumn(name="Internal note", role="ignored"),
    ]


def test_table_rows_column_roles_and_key() -> None:
    doc = parse(fixture_bytes("fees.xlsx"), filename="fees.xlsx")
    result = split(doc, settings(strategies=["table_rows"], columns=[c.model_dump() for c in fee_columns()]))
    first = result.chunks[0]
    assert first.kind == "row"
    assert "Product: Everyday Account" in first.indexed_text
    assert "Balance band: <= $250,000" in first.indexed_text
    assert "Monthly fee" not in first.indexed_text
    assert "Monthly fee: 5" in first.text
    assert "legacy pricing" not in first.text and "Internal note" not in first.metadata
    assert first.metadata["monthly_fee"] == "5"
    assert first.metadata["row_key"] == "Everyday Account"


def test_table_rows_parses_bands() -> None:
    doc = parse(fixture_bytes("fees.xlsx"), filename="fees.xlsx")
    result = split(doc, settings(strategies=["table_rows"], columns=[c.model_dump() for c in fee_columns()]))
    assert [c.row_band for c in result.chunks] == [(0, 250_000), (250_001, 1_000_000), (1_000_000, None), None]
    assert any("'any balance'" in n for n in result.notes)


def test_table_rows_without_tables_falls_back() -> None:
    result = split(md(f"# Fees\n\n{sentences(3)}"), settings(strategies=["table_rows"]))
    assert len(result.chunks) == 1 and result.chunks[0].kind == "chunk"
    assert any("no tables" in n for n in result.notes)


def faq_reply(prompt: str) -> str:
    section = re.search(r"Section: (.*)", prompt)
    name = section.group(1) if section else "this"
    return json.dumps({"questions": [f"What does {name} cover?", f"Who handles {name}?", f"When does {name} apply?"]})


def approved(*steps: str) -> dict[str, Any]:
    return {"status": "approved", "approvedSteps": list(steps), "requestedBy": "owner-a", "decidedBy": "owner-b"}


def test_faq_goes_through_model_client_only() -> None:
    doc = parse(fixture_bytes("help.html"), filename="help.html", clean=True)
    fake = FakeModelClient(respond=faq_reply)
    result = split(
        doc,
        settings(strategies=PRESETS["help_centre"], model="ingest-small", approval=approved("faq")),
        model=fake,
    )
    text_chunks = [c for c in result.chunks if c.kind != "row"]
    assert len(fake.calls) == len(text_chunks) == result.counts.model_calls
    assert {c.alias for c in fake.calls} == {"ingest-small"}
    assert all(len(c.questions or []) == 3 for c in text_chunks)
    assert sum(u.kind == "question" for u in result.index_units()) == result.counts.questions

    package = Path(knowledge_ingest.__file__).parent
    provider_import = re.compile(
        r"^\s*(import|from)\s+(openai|anthropic|httpx|requests|aiohttp|urllib\.request)\b", re.M
    )
    offenders = [str(p) for p in package.rglob("*.py") if provider_import.search(p.read_text())]
    assert offenders == []


def test_ai_step_waits_for_approval() -> None:
    doc = md(f"# Help\n\n{sentences(3)}")
    pending = settings(
        strategies=["structure", "faq"], model="ingest-small", approval={"status": "pending", "requestedBy": "a"}
    )
    fake = FakeModelClient(respond=faq_reply)

    synced = split(doc, pending, model=fake)
    assert fake.calls == []
    assert synced.chunks[0].questions is None
    assert any("approval" in n for n in synced.notes)

    previewed = split(doc, pending, model=fake, preview=True)
    assert len(fake.calls) == 1
    assert previewed.counts.questions == 3


@pytest.mark.parametrize("reply", ['{"groups": [[0, 2], [1]]}', '{"groups": [[0], [1]]}', "Sections 0 and 1 match."])
def test_topic_reply_cannot_drop_sections(reply: str) -> None:
    doc = md("# A\n\nAlpha text.\n\n# B\n\nBravo text.\n\n# C\n\nCharlie text.")
    result = split(
        doc,
        settings(strategies=["topic"], model="ingest-small", approval=approved("topic")),
        model=FakeModelClient(replies=[reply]),
    )
    assert [c.text for c in result.chunks] == ["Alpha text.", "Bravo text.", "Charlie text."]
    assert any("split by structure" in n for n in result.notes)


PAGE = """<html><body><nav class="nav">{nav}</nav><main><h1>Card limits</h1><p>{body}</p></main>
<footer>{footer}</footer></body></html>"""


def test_furniture_change_keeps_digest() -> None:
    clean = settings(strategies=["clean", "structure"])

    def digest(nav: str, footer: str, body: str) -> str:
        page = PAGE.format(nav=nav, footer=footer, body=body).encode()
        return document_digest(parse(page, filename="p.html", clean=True), clean)

    base = digest("Home | Cards", "Copyright 2025", "The daily limit is $1,000.")
    assert digest("Home | Cards | Loans", "Copyright 2026", "The daily  limit is $1,000.") == base
    assert digest("Home | Cards", "Copyright 2025", "The daily limit is $2,000.") != base


def test_pdf_to_row_chunks_end_to_end() -> None:
    doc = parse(fixture_bytes("policy.pdf"), filename="policy.pdf")
    result = split(doc, settings(strategies=["table_rows", "context_headers"]))
    rows = [c for c in result.chunks if c.kind == "row"]
    assert [r.metadata["row_key"] for r in rows] == ["Classic", "Gold", "Platinum"]
    gold = rows[1]
    assert gold.text == "Card: Gold\nAnnual fee: $95\nForeign transaction fee: 2%"
    assert gold.metadata["table_caption"] == "Table 1 Annual fees by card"
    assert gold.page == 1
    assert gold.indexed_text.startswith("Card Fees Policy > 1 Annual fees\n\n")
    prose = [c for c in result.chunks if c.kind == "chunk"]
    assert [c.section_path for c in prose] == [["1 Annual fees"], ["2 Late payment"]]
    assert prose[1].page == 2
