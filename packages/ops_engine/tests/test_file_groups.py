"""Group by and Ready when, by failure mode: a file grouped into the wrong batch or none, a group read before it is
complete or never, and a rule that cannot be read saved without naming the setting at fault."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ops_engine.file_groups import (
    FileFields,
    Group,
    RuleError,
    formula_values,
    group_by,
    group_of,
    is_marker,
    parse_pattern,
    parse_ready,
    ready,
)

NOW = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)


def test_patterns_formulas_and_ready_rules() -> None:
    # One subfolder per batch, wherever the watched folder sits in the source.
    batch = parse_pattern("{batch}/*")
    assert group_of(batch, FileFields("Invoices/Batch001/inv-1.pdf")) == Group("Batch001", {"batch": "Batch001"})
    assert group_of(batch, FileFields("inv-1.pdf")) is None
    # Named parts in a deeper convention name the group in order; a file outside it joins none.
    claims = parse_pattern("{year}/{month}/{client}/*.pdf")
    assert group_of(claims, FileFields("Claims/2026/11/acme/c-1.pdf")) == Group(
        "2026/11/acme", {"year": "2026", "month": "11", "client": "acme"}
    )
    assert group_of(claims, FileFields("Claims/2026/11/acme/c-1.csv")) is None
    assert group_of(batch, FileFields("A/B1/x.pdf")).key != group_of(batch, FileFields("A/B2/x.pdf")).key  # type: ignore[union-attr]
    # A formula is evaluated by the caller over the file's values.
    assert group_by("=split(name, '_')[0]") == "split(name, '_')[0]"
    assert formula_values(FileFields("Drop/acme_7.pdf", NOW))["name"] == "acme_7.pdf"
    assert group_by("  ") is None
    # A marker readies its group and is no row; the group waits until it arrives.
    marker = parse_ready({"kind": "marker", "pattern": "_READY"})
    files = [FileFields("B1/a.pdf"), FileFields("B1/b.pdf")]
    assert not ready(marker, files, NOW)
    assert ready(marker, [*files, FileFields("B1/_READY")], NOW) and is_marker(marker, FileFields("B1/_READY"))
    # Quiet minutes: ready only once nothing changed for that long.
    quiet = parse_ready({"kind": "quiet", "minutes": 30})
    assert not ready(quiet, [FileFields("d/a.pdf", NOW - timedelta(minutes=29))], NOW)
    assert ready(quiet, [FileFields("d/a.pdf", NOW - timedelta(minutes=30))], NOW)
    # The manifest's count, and at each check.
    count = parse_ready({"kind": "manifest_count"})
    assert not ready(count, files, NOW, manifest_count=None) and ready(count, files, NOW, manifest_count=2)
    assert ready(parse_ready(None), [], NOW)
    # A rule that cannot be read names its field.
    for bad, field in (
        (lambda: parse_pattern("{batch/*"), "groupBy"),
        (lambda: parse_pattern("{a}/{a}/*"), "groupBy"),
        (lambda: parse_ready({"kind": "marker", "pattern": ""}), "readyWhen.pattern"),
        (lambda: parse_ready({"kind": "quiet", "minutes": 0}), "readyWhen.minutes"),
        (lambda: parse_ready({"kind": "sometimes"}), "readyWhen.kind"),
    ):
        with pytest.raises(RuleError) as refused:
            bad()
        assert refused.value.field == field
