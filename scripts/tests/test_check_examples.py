"""A broken example.yaml fails the offline checker."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_examples import (
    CAPABILITIES,
    SCHEMA,
    built_nodes,
    check_folder,
    json,
    load_capabilities,
    render_registry,
    validate_meta,
)


def test_a_broken_example_yaml_fails(tmp_path: Path) -> None:
    (tmp_path / "example.yaml").write_text("title: Missing everything else\n")
    schema = json.loads(SCHEMA.read_text())
    _meta, problems = check_folder(tmp_path, schema)
    assert problems
    assert any("missing" in p for p in problems)


def test_built_nodes_include_classify() -> None:
    assert "ops.ai.classify" in built_nodes()


def test_schema_requires_track() -> None:
    schema = json.loads(SCHEMA.read_text())
    problems = validate_meta({"id": "x", "title": "X"}, schema)
    assert "missing track" in problems


def test_capability_catalog_lists_polished_ids() -> None:
    rows, problems = load_capabilities()
    assert not problems, problems
    ids = {row["id"] for row in rows}
    assert "chat.ask-once" in ids
    assert "skill.publish-and-pick" in ids
    assert CAPABILITIES.is_file()
    registry = render_registry(rows, [])
    assert any(c["id"] == "chat.ask-once" and c.get("deepLink") == "#chat.ask-once" for c in registry["capabilities"])
