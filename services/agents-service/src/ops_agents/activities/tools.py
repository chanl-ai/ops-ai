"""Python-local demo tools behind the kernel's ToolExecutor port, until calls go through Protobox's tool gateway.

`lookup` tools read a dataset from the catalogue and return a record view; `draft` tools are write tools that only
run once approved, and record each execution by idempotency key so a repeat returns the first result.
"""

from __future__ import annotations

from typing import Any, Protocol

from ops_agent_kernel.ports import ToolOutcome
from ops_service_kit.ids import new_id, now_iso

from .catalog import Catalog, ToolDefinition


def fill(template: str, values: dict[str, Any]) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out


class LocalToolExecutor:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self._executed: dict[str, ToolOutcome] = {}

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        definition = self._catalog.tool(tool)
        if definition is None:
            return ToolOutcome(False, f"Tool {tool} is not granted to this agent.")
        if definition.kind == "lookup":
            return self._lookup(definition, arguments)
        if definition.access != "read" and not approval_token:
            # The kernel only runs a gated tool after a decision; a call without one is refused, never executed.
            return ToolOutcome(False, "This action needs an approval before it can run.")
        if key in self._executed:
            return self._executed[key]
        outcome = self._draft(definition, arguments)
        self._executed[key] = outcome
        return outcome

    def _lookup(self, d: ToolDefinition, arguments: dict[str, Any]) -> ToolOutcome:
        rows = self._catalog.datasets.get(d.dataset or "", [])
        needles = [str(v).strip().lower() for v in arguments.values() if str(v).strip()]
        match = next(
            (r for r in rows if any(n in str(r.get(f, "")).lower() for n in needles for f in d.match_fields)),
            None,
        )
        if match is None:
            return ToolOutcome(True, {"found": False, "message": "No record matches that search."})
        view = {
            "kind": "record",
            "title": fill(d.view_title or d.name, match),
            "status": match.get("status"),
            "fields": [{"label": label, "value": fill(tpl, match)} for label, tpl in d.view_fields],
        }
        return ToolOutcome(True, {"found": True, **match}, view)

    def _draft(self, d: ToolDefinition, arguments: dict[str, Any]) -> ToolOutcome:
        reference = new_id("ref").upper().replace("REF_", "NB-")
        result = fill(d.approval.result, {**arguments, "reference": reference}) if d.approval else "Done."
        return ToolOutcome(
            True, {"status": "completed", "reference": reference, "completedAt": now_iso(), "result": result}
        )


class ReplySender(Protocol):
    async def send(self, *, key: str, to: str, subject: str, body: str, approval_token: str | None = None) -> str: ...


class LocalReplySender:
    """Stub for the mailbox's send-reply tool. Records each send by idempotency key, so a node that runs twice for
    the same case sends once; the real tool goes through the tool gateway with the same key."""

    def __init__(self) -> None:
        self.sent: dict[str, dict[str, str]] = {}

    async def send(self, *, key: str, to: str, subject: str, body: str, approval_token: str | None = None) -> str:
        if key not in self.sent:
            reference = new_id("mail").upper().replace("MAIL_", "OUT-")
            self.sent[key] = {"reference": reference, "to": to, "subject": subject, "body": body}
        return self.sent[key]["reference"]
