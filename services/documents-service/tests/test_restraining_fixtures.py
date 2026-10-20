"""The synthetic restraining notices (c-248), by failure mode: an expected value the file does not print on the page it
names, so a correct reader fails its sample (F1); a value that should sit only on a later page printed on page 1 too,
so the cross-page case proves nothing (F2); a scan that carries a text layer, so OCR is never exercised (F3); OCR
that cannot read the identifiers on the degraded pages (F4); expected.json out of step with notices.json after an
edit (F5); the seeded restraining_notice naming a file or a field that does not exist (F6)."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from typing import Any, cast

import httpx
import pdfplumber
import pytest

from ops_extract.checks import fold
from ops_extract.layout import build_layout, page_text
from ops_extract.pages import Pages
from ops_ingest.parsers.ocr import OcrUnavailableError, TesseractEngine

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
# The restraining notices (c-248) and the tax levies (c-270), each file named by its folder.
DATASETS = (("restraining", "notices.json", "photographed"), ("tax_levy", "levies.json", "tax_levy"))
EXPECTED: dict[str, dict[str, Any]] = {
    f"{folder}/{name}": entry
    for folder, _, _ in DATASETS
    for name, entry in json.loads((FIXTURES / folder / "expected.json").read_text()).items()
}
TEXT = sorted(name for name, e in EXPECTED.items() if not e.get("imageOnly"))
IMAGES = sorted(name for name, e in EXPECTED.items() if e.get("imageOnly"))


def script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def printed_text(name: str) -> dict[int, str]:
    """Each page's text layer, folded: what the file itself prints, whatever a reader later makes of it."""
    with pdfplumber.open(io.BytesIO((FIXTURES / name).read_bytes())) as doc:
        return {n: fold(p.extract_text() or "") for n, p in enumerate(doc.pages, start=1)}


def read(name: str, *, ocr: bool = False) -> Pages:
    """The file as an extraction reads it: its layout's page text (c-247)."""
    return page_text(build_layout((FIXTURES / name).read_bytes(), filename=name, ocr=ocr))


def printed(entry: dict[str, Any]) -> dict[str, tuple[str, int]]:
    """Each non-empty expected value with the page it sits on."""
    pages = cast(dict[str, int], entry.get("pages") or {})
    return {k: (str(v), pages.get(k, 1)) for k, v in cast(dict[str, Any], entry["expected"]).items() if v is not None}


@pytest.mark.parametrize("name", TEXT)
def test_every_expected_value_is_printed_on_its_page(name: str) -> None:
    texts = printed_text(name)
    missing = [f"{k} p{p}: {v}" for k, (v, p) in printed(EXPECTED[name]).items() if fold(v) not in texts.get(p, "")]
    assert missing == [], texts


@pytest.mark.parametrize("name", TEXT)
def test_an_extraction_reads_every_expected_value_on_its_page(name: str) -> None:
    """The page text the model is given and quotes are checked against holds each value, titles and case lines
    included (c-260)."""
    texts = {n: fold(t) for n, t in read(name).texts.items()}
    missing = [f"{k} p{p}: {v}" for k, (v, p) in printed(EXPECTED[name]).items() if fold(v) not in texts.get(p, "")]
    assert missing == [], texts


@pytest.mark.parametrize("name", [n for n in TEXT if EXPECTED[n].get("pages")])
def test_a_later_page_value_is_not_also_on_page_one(name: str) -> None:
    first = printed_text(name)[1]
    later = {k: v for k, (v, p) in printed(EXPECTED[name]).items() if p > 1}
    assert later and [k for k, v in later.items() if fold(v) in first] == [], first


@pytest.mark.parametrize("name", IMAGES)
def test_a_scan_has_no_text_layer(name: str) -> None:
    assert set(printed_text(name).values()) == {""}, f"{name} carries text, so OCR is never exercised"


@pytest.mark.parametrize("name", IMAGES)
def test_ocr_reads_the_identifiers_on_a_degraded_page(name: str) -> None:
    try:
        TesseractEngine()
    except OcrUnavailableError as e:
        pytest.skip(str(e))
    text = fold("\n".join(read(name, ocr=True).texts.values()))
    keys = ("case_no", "ssn_full", "debtor_name", "debtor_address")
    wanted = {k: v for k, (v, _) in printed(EXPECTED[name]).items() if k in keys}
    assert wanted and [f"{k}: {v}" for k, v in wanted.items() if fold(v) not in text] == [], text


@pytest.mark.parametrize(("folder", "source", "family"), DATASETS)
def test_expected_json_is_what_the_generator_makes_from_its_source(folder: str, source: str, family: str) -> None:
    here = FIXTURES / folder
    _, expected = script("make_restraining_fixtures").catalogue(json.loads((here / source).read_text()), family)
    on_disk = json.loads((here / "expected.json").read_text())
    assert json.loads(json.dumps(expected)) == on_disk, "run scripts/make_restraining_fixtures.py and commit"


@pytest.mark.parametrize("kind", ["RESTRAINING_NOTICE", "TAX_LEVY", "SUPPLIER_INVOICE", "BANK_STATEMENT"])
def test_a_seeded_type_names_real_files_and_fields(kind: str) -> None:
    seed = script("seed_document_types")
    definition, samples, folder = seed.SEEDED[kind]
    keys = {f["key"] for f in definition["fields"]}
    assert len(samples()) <= 20, "a test run reads at most 20 samples"
    for name, expected in samples().items():
        assert (folder / name).is_file(), name
        assert set(expected) <= keys, f"{name}: {set(expected) - keys}"


def test_the_seed_leaves_an_existing_type_alone() -> None:
    """Create-only: a seed that made a version on every start dropped the templates a person had saved."""
    seed = script("seed_document_types")
    calls: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        return httpx.Response(409, json={"success": False, "error": {"code": "name_taken"}})

    documents = httpx.Client(transport=httpx.MockTransport(answer), base_url="http://documents")
    said = seed.seed_type(documents, documents, seed.SUPPLIER_INVOICE, {}, FIXTURES)
    assert said == "supplier_invoice: already there" and calls == ["POST /v1/document-types"], calls
