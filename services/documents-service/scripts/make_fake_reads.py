"""Writes tests/fixtures/fake-model/script.json (c-255): the fake OpenAI's answers for every fixture of the four
seeded document types, so a use case drives the model path end to end without a real model call.

    uv run python scripts/make_fake_reads.py

For each fixture two rules: classify (the prompt starts "Document types:") answers its type, and extract (the prompt
starts "Fields:") answers each field with the value expected.json holds and, when that text is printed on the page,
the same text as its quote. Each rule is keyed on a value printed only in that fixture, checked against the text an
extraction reads (the layout's page text, OCR'd for scans); a fixture with no such value gets no rules, and a value
not printed gets no quote, so the checks send it to review rather than ground it on nothing."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

from ops_extract.layout import build_layout, page_text

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "tests" / "fixtures"
OUT = FIXTURES / "fake-model" / "script.json"
# A marker shorter than this could be printed in another fixture by chance.
MARKER_CHARS = 6
# A page of no seeded type (c-335): classify answers that none fits, so a Detect read is saved as not recognised.
UNKNOWN = "Staff canteen menu for the week"


def _seed() -> Any:
    spec = importlib.util.spec_from_file_location("seed_document_types", HERE / "seed_document_types.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_document_types"] = module
    spec.loader.exec_module(module)
    return module


def texts(seeded: dict[str, Any]) -> dict[tuple[str, str], tuple[dict[int, str], dict[str, Any]]]:
    """(type id, file) -> (the text an extraction reads, by page, and the expected entry), for every seeded fixture."""
    out: dict[tuple[str, str], tuple[dict[int, str], dict[str, Any]]] = {}
    for definition, _, folder in seeded.values():
        entries: dict[str, dict[str, Any]] = json.loads((folder / "expected.json").read_text())
        for name, entry in sorted(entries.items()):
            layout = build_layout((folder / name).read_bytes(), filename=name, ocr=bool(entry.get("imageOnly")))
            out[(definition["id"], name)] = (page_text(layout).texts, entry)
    return out


def main() -> None:
    seeded = _seed().SEEDED
    fields_of = {d["id"]: d["fields"] for d, _, _ in seeded.values()}
    every = texts(seeded)
    rules: list[dict[str, Any]] = []
    skipped: list[str] = []
    for (type_id, name), (pages, entry) in every.items():
        text = "\n".join(pages.values())
        expected: dict[str, Any] = entry["expected"]
        # A scan of a text fixture expects the same values, so one rule answering both is right.
        others = [
            "\n".join(t.values())
            for key, (t, e) in every.items()
            if key != (type_id, name) and e["expected"] != expected
        ]
        printed = [v for v in expected.values() if isinstance(v, str) and len(v) >= MARKER_CHARS and v in text]
        marker = next((v for v in printed if not any(v in o for o in others)), None)
        if marker is None:
            skipped.append(name)
            continue
        keyed = re.escape(marker)
        reason = f"{marker} is printed on the page"
        rules.append(
            {
                "when": f"^Document types:.*{keyed}",
                "tool": "final_result",
                "arguments": {"typeId": type_id, "confidence": 0.95, "reason": reason},
            }
        )
        answer: dict[str, Any] = {}
        for f in fields_of[type_id]:
            v = expected.get(f["key"])
            said = str(v) if v is not None else None
            page = next((n for n, t in sorted(pages.items()) if said and said in t), None)
            answer[f["key"]] = {"value": said, "quote": said if page else None, "page": page}
        rules.append({"when": f"^Fields:.*{keyed}", "tool": "final_result", "arguments": answer})
    unknown = {"typeId": None, "confidence": 0.2, "reason": "A canteen menu is none of the team's document types"}
    rules.append({"when": f"^Document types:.*{re.escape(UNKNOWN)}", "tool": "final_result", "arguments": unknown})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"rules": rules}, indent=1) + "\n")
    missing = ", ".join(skipped) or "none"
    print(f"{(len(rules) - 1) // 2} fixtures with rules, and one page of no type; none for {missing}")


if __name__ == "__main__":
    main()
