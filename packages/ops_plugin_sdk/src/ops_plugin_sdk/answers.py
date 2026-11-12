"""Where a system reports a failure inside a successful answer: Slack answers 200 with `ok: false` and its code at
`error`, a GraphQL API answers 200 with a list at `errors`. A plugin names that path as `error_when`; both executors
read every JSON answer of the plugin through `answer_error`, so a declared failure never passes as a success."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from .errors import NeedsReconnect, PluginError, Refused
from .manifest import Manifest, SignInError
from .paging import at

MAX_WORDS = 300


def error_rule(manifest: Manifest) -> dict[str, Any] | None:
    """What an executor needs to read the plugin's answers, as plain data carried on the call's operation."""
    if manifest.error_when is None:
        return None
    return {
        "path": manifest.error_when,
        "app": manifest.title,
        "sign_in_errors": [e.model_dump() for e in manifest.connection.sign_in_errors],
    }


def _words(found: Any) -> str | None:
    """The system's own code or message: a text value as it is, a list's first item, an object's message or code."""
    if isinstance(found, list):
        found = cast(list[Any], found)[0] if found else None
    if isinstance(found, dict):
        item = cast(dict[str, Any], found)
        found = item.get("message") or item.get("code") or item.get("error")
    if found is None or found is False or found == "":
        return None
    return "an error" if found is True else str(found)[:MAX_WORDS]


def answer_error(answer: Any, rule: Mapping[str, Any] | None) -> PluginError | None:
    """The failure an answer reports at the rule's path, or None for a success. A code the plugin lists among its
    `sign_in_errors` asks for the account to connect again, in the plugin's own words."""
    if not rule:
        return None
    code = _words(at(answer, str(rule["path"])))
    if code is None:
        return None
    app = str(rule.get("app") or "The system")
    for entry in cast(list[dict[str, Any]], rule.get("sign_in_errors") or []):
        known = SignInError.model_validate(entry)
        if known.matches(code, None):
            return NeedsReconnect((known.say or f"{app} asks for the account to connect again.").replace("{app}", app))
    return Refused(f"{app} refused the call: {code.rstrip('.')}.")
