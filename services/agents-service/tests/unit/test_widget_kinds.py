"""Generic widget kinds (c-176), by failure mode: data outside a kind's schema drawn; a kind carrying a link, script,
HTML or image source; an oversized kind; an unknown kind; a gallery sample the agent could not emit; the console's copy
of the kind schemas drifting from the kernel's; a template that binds a kind not filling it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ops_agent_kernel import kinds, layout, present

ROOT = Path(__file__).resolve().parents[4]
SAMPLES: dict[str, list[dict[str, Any]]] = json.loads(
    (ROOT / "apps/console/src/lib/widgets/kind-samples.json").read_text()
)


def show(kind: str, data: Any) -> tuple[dict[str, Any] | None, str]:
    return present.run({"kind": kind, "data": data}, None)  # pyright: ignore[reportArgumentType] - settings unused for kinds


@pytest.mark.parametrize("kind", kinds.KINDS)
def test_every_gallery_sample_is_one_the_agent_can_emit_in_two_industries(kind: str) -> None:
    samples = SAMPLES[kind]
    assert len({s["industry"] for s in samples}) >= 2, f"{kind} shows one industry"
    for s in samples:
        part, said = show(kind, s["data"])
        assert part is not None, f"{kind} {s['industry']}: {said}"
        assert part["kind"] == kind and part["layout"]["type"] == kind


def test_data_outside_the_schema_is_refused_with_the_field_named() -> None:
    part, said = show("tracker", {"steps": [{"label": "Packed", "state": "shipped"}]})
    assert part is None and "/steps/0/state" in said, said
    part, said = show(
        "receipt", {"title": "x", "currency": "dollars", "lines": [{"label": "a", "amount": 1}], "total": 1}
    )
    assert part is None and "currency" in said, said


@pytest.mark.parametrize(
    ("kind", "data"),
    [
        ("contact", {"name": "Priya", "url": "https://evil.example"}),
        (
            "entity",
            {"title": "x", "fields": [], "actions": [{"label": "Go", "reply": "go", "href": "javascript:alert(1)"}]},
        ),
        ("document", {"name": "a.pdf", "passage": "p", "fileId": "https://evil.example/a.pdf"}),
        ("quote", {"passage": "p", "source": "s", "html": "<script>alert(1)</script>"}),
        ("entity", {"title": "x", "fields": [], "image": "https://evil.example/a.png"}),
    ],
)
def test_a_kind_carries_no_link_script_html_or_image_source(kind: str, data: dict[str, Any]) -> None:
    part, _ = show(kind, data)
    assert part is None, f"{kind} accepted {data}: {part}"


def test_an_oversized_kind_is_refused() -> None:
    many = [{"at": str(i), "title": "event"} for i in range(51)]  # one past the 50 a list may hold
    part, said = show("timeline", {"events": many})
    assert part is None and "events" in said, said
    long = {"steps": [{"label": "x" * 1999, "state": "done"} for _ in range(9)]}
    part, said = show("plan", {"title": "p", **long})
    assert part is None and "characters of text" in said, said


def test_an_unknown_kind_is_refused() -> None:
    part, said = show("hologram", {"x": 1})
    assert part is None and "kind must be one of" in said, said
    with pytest.raises(layout.LayoutError, match="not in the catalogue"):
        layout.check({"type": "hologram"})


def test_the_consoles_copy_of_the_kind_schemas_is_the_kernels() -> None:
    assert kinds.CONSOLE_COPY.read_text() == kinds.render(), "run python -m ops_agent_kernel.kinds --write"


def test_a_template_binds_a_kind_like_any_node() -> None:
    tree = {
        "type": "card",
        "title": {"$bind": "/title"},
        "children": [{"type": "tracker", "steps": {"$bind": "/steps"}}],
    }
    schema = {"type": "object", "properties": {"title": {"type": "string"}, "steps": {"type": "array"}}}
    filled = layout.fill(tree, schema, {"title": "Order 1182", "steps": [{"label": "Packed", "state": "done"}]})
    assert filled["children"] == [{"type": "tracker", "steps": [{"label": "Packed", "state": "done"}]}]
