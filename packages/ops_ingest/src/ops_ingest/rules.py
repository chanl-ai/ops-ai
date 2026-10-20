# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Source include and exclude rules (spec 15.1, console `Rule`).

Exclude rules win. With any include rule, an item must match one. The decision names the rule that
excluded the item in words, which the console shows as `excludedBy`.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel

RuleField = Literal["path", "title", "mime", "modified_after", "size_under"]
_UNITS = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3}


class Rule(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
    id: str
    kind: Literal["include", "exclude"]
    field: RuleField
    value: str

    @field_validator("field", mode="before")
    @classmethod
    def _snake_field(cls, value: object) -> object:
        # The console sends `modifiedAfter` and `sizeUnder`.
        return {"modifiedAfter": "modified_after", "sizeUnder": "size_under"}.get(str(value), value)


class ItemFacts(BaseModel):
    path: str
    title: str
    mime: str
    modified: dt.datetime
    size: int


class RuleDecision(BaseModel):
    included: bool
    rule_id: str | None = None
    excluded_by: str | None = None


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """`**` crosses folders, `*` and `?` stay within one. A pattern without `/` matches the file name anywhere."""
    pattern = pattern.strip().lstrip("/")
    if "/" not in pattern:
        pattern = "**/" + pattern
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z", re.IGNORECASE)


def parse_size(value: str) -> int:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmg]?b)?\s*", value, re.IGNORECASE)
    if m is None:
        raise ValueError(f"Not a size: {value!r}")
    return int(float(m.group(1)) * _UNITS[(m.group(2) or "b").lower()])


def _parse_date(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.strip())
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def matches(rule: Rule, item: ItemFacts) -> bool:
    match rule.field:
        case "path":
            return glob_to_regex(rule.value).match(item.path.lstrip("/")) is not None
        case "title":
            return rule.value.strip().lower() in item.title.lower()
        case "mime":
            return fnmatch.fnmatch(item.mime.lower(), rule.value.strip().lower())
        case "modified_after":
            modified = item.modified if item.modified.tzinfo else item.modified.replace(tzinfo=dt.UTC)
            return modified > _parse_date(rule.value)
        case "size_under":
            return item.size < parse_size(rule.value)


def describe(rule: Rule) -> str:
    what = {
        "path": f"path matches {rule.value}",
        "title": f"title contains “{rule.value}”",
        "mime": f"type is {rule.value}",
        "modified_after": f"modified after {rule.value}",
        "size_under": f"size under {rule.value}",
    }[rule.field]
    return f"{rule.kind.capitalize()} rule: {what}"


def evaluate_rules(rules: list[Rule], item: ItemFacts) -> RuleDecision:
    for rule in rules:
        if rule.kind == "exclude" and matches(rule, item):
            return RuleDecision(included=False, rule_id=rule.id, excluded_by=describe(rule))
    includes = [r for r in rules if r.kind == "include"]
    if includes and not any(matches(r, item) for r in includes):
        return RuleDecision(included=False, excluded_by="No include rule matches")
    return RuleDecision(included=True)
