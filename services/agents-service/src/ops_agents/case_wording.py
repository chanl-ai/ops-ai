"""A case event as a sentence (c-500): the one wording of what was done on a case, for the case page's feed and the
Activity page's case rows alike."""

from __future__ import annotations

import re
from typing import Any

FIELDS = {
    "status": "Status",
    "priority": "Priority",
    "subject": "Subject",
    "assignee": "Owner",
    "response_due_at": "First response due",
    "resolution_due_at": "Resolution due",
}


def _words(value: Any) -> str:
    text = re.sub(r"[_-]+", " ", str(value)).strip()
    return text[:1].upper() + text[1:] if text else "nothing"


def _said(actor: str, rest: str) -> str:
    return f"{actor} {rest}" if actor else rest[:1].upper() + rest[1:]


def entry(kind: str, detail: dict[str, Any], actor: str = "", names: dict[str, str] | None = None) -> str | None:
    """The event in a sentence, led by who did it when `actor` is given (the case feed) and without, where the page
    shows who did it beside the sentence (Activity); None for an event another line already tells: a run added to the
    case is told by the run's own lines, and a decision by the Human Task step that took it."""
    names = names or {}
    text = str(detail.get("text") or "").strip()
    if kind == "opened":
        return _said(actor, "opened this case")
    if kind == "note" or (kind == "run" and text):
        return _said(actor, f"added a note: {text}")
    if kind == "chat":
        return _said(actor, "added a chat")
    if kind == "link":
        return _said(actor, f"linked case {detail.get('case') or ''}".rstrip())
    if kind == "field":
        field = str(detail.get("field") or "")
        after = detail.get("after")
        if field == "status":
            return _said(actor, f"set the status to {_words(after)}")
        if field == "subject":
            return _said(actor, f"changed the subject to {after}")
        if field == "assignee":
            owner = names.get(str(after), str(after))
            return _said(actor, f"gave the case to {owner}" if after else "left the case without an owner")
        shown = after[:10] if field.endswith("_due_at") and isinstance(after, str) else _words(after)
        return _said(actor, f"changed {FIELDS.get(field, _words(field))} to {shown}")
    return None
