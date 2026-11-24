"""How a Files changed trigger groups a watched folder's files into named batches, and when a group is ready: pure
functions over a file's path, name, extension and modified time, with no naming rule of any customer in code.

Group by is a path pattern with named parts (`{batch}/*`, `{year}/{month}/{client}/*`) or, starting with `=`, a
formula the workflow's formula language evaluates over `formula_values(file)`; the caller evaluates formulas through
the expressions port, so this module stays free of I/O. A pattern matches the end of a file's path, so it does not
depend on where the watched folder sits in the source. Each distinct set of named parts is one group, named by them.

Ready when is one of: at each check; when a marker file (such as `_READY`) is in the group; after no change for a
number of minutes; when the group holds as many files as its manifest lists; or a formula."""

from __future__ import annotations

import hashlib
import posixpath
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

ReadyKind = Literal["each_check", "marker", "quiet", "manifest_count", "formula"]
READY_KINDS: tuple[ReadyKind, ...] = ("each_check", "marker", "quiet", "manifest_count", "formula")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_NAME = 300


class RuleError(ValueError):
    """A rule that cannot be used, with the setting it came from, so a save is refused naming that field."""

    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(message)
        self.field = field_name


@dataclass(frozen=True)
class Pattern:
    text: str
    parts: tuple[str, ...]
    regex: re.Pattern[str]


@dataclass(frozen=True)
class FileFields:
    """What a rule reads of one file: its path below the source (folders joined by `/`, ending in its name)."""

    path: str
    modified: datetime | None = None

    @property
    def name(self) -> str:
        return posixpath.basename(self.path)

    @property
    def extension(self) -> str:
        return posixpath.splitext(self.name)[1].lstrip(".").lower()


@dataclass(frozen=True)
class Group:
    name: str
    parts: Mapping[str, str] = field(default_factory=dict[str, str])

    @property
    def key(self) -> str:
        """A stable key for the group's name, at most 64 characters whatever the name's length."""
        return hashlib.sha256(self.name.encode()).hexdigest()


@dataclass(frozen=True)
class Ready:
    kind: ReadyKind
    marker: Pattern | None = None
    minutes: int | None = None
    formula: str | None = None


def _segment(text: str, seen: list[str], field_name: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "{":
            end = text.find("}", i)
            if end < 0:
                raise RuleError(field_name, f"{{ at {i + 1} is never closed.")
            name = text[i + 1 : end]
            if not NAME.match(name):
                raise RuleError(field_name, f"{{{name}}} is not a part name: use letters, digits and _.")
            if name in seen:
                raise RuleError(field_name, f"{{{name}}} is named twice.")
            seen.append(name)
            out.append(f"(?P<{name}>[^/]+)")
            i = end + 1
        elif ch == "}":
            raise RuleError(field_name, f"}} at {i + 1} has no {{ before it.")
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return "".join(out)


def parse_pattern(text: str, field_name: str = "groupBy") -> Pattern:
    """A path pattern: folders joined by `/`, each literal text, `{part}` for a named part and `*` for any text
    within one folder or name. Raises `RuleError` naming `field_name` for a pattern that cannot be read."""
    cleaned = text.strip().strip("/")
    if not cleaned:
        raise RuleError(field_name, "The pattern is empty.")
    seen: list[str] = []
    segments = [_segment(s, seen, field_name) for s in cleaned.split("/")]
    if any(not s for s in segments):
        raise RuleError(field_name, "The pattern has an empty folder (//).")
    return Pattern(cleaned, tuple(seen), re.compile(r"(?:^|/)" + "/".join(segments) + "$"))


def group_by(text: str | None) -> Pattern | str | None:
    """Group by as saved: None (each check is one batch), a formula (text after `=`), or a parsed pattern."""
    if text is None or not text.strip():
        return None
    if text.strip().startswith("="):
        formula = text.strip()[1:].strip()
        if not formula:
            raise RuleError("groupBy", "The formula is empty.")
        return formula
    return parse_pattern(text)


def group_of(pattern: Pattern, file: FileFields) -> Group | None:
    """The group a file belongs to by `pattern`, or None when its path does not match. The name is the named parts in
    the pattern's order joined by `/`, or the file's folder for a pattern with no named part."""
    found = pattern.regex.search(file.path.strip("/"))
    if found is None:
        return None
    parts = {p: found.group(p) for p in pattern.parts}
    name = "/".join(parts.values()) if parts else posixpath.dirname(file.path.strip("/"))
    return Group(name[:MAX_NAME] or "/", parts)


def formula_group(value: object) -> Group | None:
    """The group a formula's value names: its text, or None for an empty value (the file joins no group)."""
    text = "" if value is None else str(value).strip()
    return Group(text[:MAX_NAME]) if text else None


def formula_values(file: FileFields) -> dict[str, object]:
    """What a Group by or Ready when formula reads of a file."""
    return {
        "path": file.path,
        "folders": file.path.strip("/").split("/")[:-1],
        "name": file.name,
        "extension": file.extension,
        "modified": file.modified.isoformat() if file.modified else None,
    }


def parse_ready(rule: Mapping[str, object] | None) -> Ready:
    """Ready when as saved (`{kind, pattern?, minutes?, formula?}`); none means at each check."""
    if not rule:
        return Ready("each_check")
    kind = rule.get("kind")
    if kind not in READY_KINDS:
        raise RuleError("readyWhen.kind", f"{kind!r} is not one of {', '.join(READY_KINDS)}.")
    if kind == "marker":
        return Ready("marker", marker=parse_pattern(str(rule.get("pattern") or ""), "readyWhen.pattern"))
    if kind == "quiet":
        minutes = rule.get("minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= 1440:
            raise RuleError("readyWhen.minutes", "Minutes is a whole number from 1 to 1440.")
        return Ready("quiet", minutes=minutes)
    if kind == "formula":
        formula = str(rule.get("formula") or "").strip()
        if not formula:
            raise RuleError("readyWhen.formula", "The formula is empty.")
        return Ready("formula", formula=formula)
    return Ready(kind)


def is_marker(rule: Ready, file: FileFields) -> bool:
    """Whether the file only says its group is ready, so it is no row of the batch."""
    return rule.marker is not None and rule.marker.regex.search(file.name) is not None


def ready(rule: Ready, group_files: Sequence[FileFields], now: datetime, *, manifest_count: int | None = None) -> bool:
    """Whether a group holding `group_files` is ready now. A formula rule is evaluated by the caller and answers
    False here; `manifest_count` is the number of files the group's manifest lists, None before it is read."""
    if rule.kind == "each_check":
        return True
    if rule.kind == "marker":
        return any(is_marker(rule, f) for f in group_files)
    if rule.kind == "quiet":
        times = [f.modified for f in group_files if f.modified is not None]
        return bool(times) and max(times) <= now - timedelta(minutes=rule.minutes or 0)
    if rule.kind == "manifest_count":
        return manifest_count is not None and len(group_files) >= manifest_count
    return False
