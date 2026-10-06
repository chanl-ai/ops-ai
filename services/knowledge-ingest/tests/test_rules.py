# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from knowledge_ingest.rules import ItemFacts, Rule, evaluate_rules


def item(**kw: Any) -> ItemFacts:
    base: dict[str, Any] = {
        "path": "policies/cards/fees.docx",
        "title": "Card fees",
        "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "modified": dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
        "size": 2 * 1024 * 1024,
    }
    return ItemFacts(**{**base, **kw})


def rule(kind: str, field: str, value: str, rule_id: str = "r1") -> Rule:
    # Console JSON uses camelCase field names.
    return Rule.model_validate({"id": rule_id, "kind": kind, "field": field, "value": value})


def test_exclude_rule_applied_and_named() -> None:
    decision = evaluate_rules([rule("exclude", "path", "archive/**")], item(path="archive/2019/old/fees.pdf"))
    assert not decision.included
    assert decision.rule_id == "r1"
    assert decision.excluded_by == "Exclude rule: path matches archive/**"


def test_include_rules_require_a_match() -> None:
    decision = evaluate_rules([rule("include", "path", "policies/lending/**")], item())
    assert not decision.included
    assert decision.excluded_by == "No include rule matches"


def test_exclude_wins_over_include() -> None:
    rules = [rule("include", "path", "policies/**", "inc"), rule("exclude", "title", "fees", "exc")]
    decision = evaluate_rules(rules, item())
    assert not decision.included and decision.rule_id == "exc"


def test_single_star_stays_in_folder() -> None:
    rules = [rule("exclude", "path", "policies/*.docx")]
    assert evaluate_rules(rules, item(path="policies/fees.docx")).included is False
    assert evaluate_rules(rules, item(path="policies/cards/fees.docx")).included is True


@pytest.mark.parametrize(
    ("field", "value", "matching", "other"),
    [
        ("title", "FEES", {"title": "Card fees"}, {"title": "Card limits"}),
        ("mime", "application/pdf", {"mime": "application/pdf"}, {}),
        ("mime", "image/*", {"mime": "image/png"}, {}),
        ("modifiedAfter", "2026-04-01", {}, {"modified": dt.datetime(2026, 3, 1, tzinfo=dt.UTC)}),
        ("sizeUnder", "5 MB", {}, {"size": 6 * 1024 * 1024}),
        ("sizeUnder", "500KB", {"size": 400 * 1024}, {}),
    ],
)
def test_rule_fields(field: str, value: str, matching: dict[str, Any], other: dict[str, Any]) -> None:
    rules = [rule("exclude", field, value)]
    assert evaluate_rules(rules, item(**matching)).included is False
    assert evaluate_rules(rules, item(**other)).included is True
