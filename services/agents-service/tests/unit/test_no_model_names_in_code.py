"""No vendor model name is written into service or package code (staging defect, 2026-10-18): a default alias named
after a vendor model was refused by models-service's alias pattern and tied every deployment to one provider. Model
names belong in configuration and in models-service's alias rows; code names aliases. String literals are read from
the code, so a comment or a test fixture may still name a model."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
VENDOR = re.compile(r"\b(gpt-\d|gpt-4o|o[134]-mini|claude-\d|claude-(opus|sonnet|haiku)|gemini-\d)", re.I)


def test_no_vendor_model_name_in_code() -> None:
    found: list[str] = []
    for path in sorted([*ROOT.glob("packages/*/src/**/*.py"), *ROOT.glob("services/*/src/**/*.py")]):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and VENDOR.search(node.value):
                found.append(f"{path.relative_to(ROOT)}:{node.lineno} {node.value[:60]!r}")
    assert found == [], "name an alias and configure the model instead:\n" + "\n".join(found)
