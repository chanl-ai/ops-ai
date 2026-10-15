"""Gateway call rows as the console's ToolCallRow (apps/console/src/lib/types/governance.ts), with the identity
fields agreed with the console: `subject` from the call's `sub` (the verified calling service), `actor` from its
`act`, the run, the step, the approval token's fingerprint, the decision and the deny reason. The workflow a call ran
for comes from the subject when it is one, else from the actor."""

from __future__ import annotations

from typing import Any, cast

# A replay ran nothing, so it is its own status, not a success; a write refused because the same one was running is a
# denial. Both stay out of a module's call counts (CallLog.traffic) and the 409 counts as denied.
STATUS = {
    "ok": "ok",
    "replayed": "replayed",
    "error": "error",
    "refused": "denied",
    "in_progress": "denied",
    "running": "ok",
}
SUBJECT_KINDS = {"user": "user", "workflow": "workflow", "process": "process"}
ACTOR_KINDS = {"user": "user", "agent": "agent", "workflow": "workflow", "graph": "workflow"}


def _identity(value: str, kinds: dict[str, str], names: dict[str, str]) -> dict[str, str]:
    """`kind:id` principals name their kind; anything else is a service. Workflows show the name their approval
    recorded, or their id."""
    prefix, _, rest = value.partition(":")
    kind = kinds.get(prefix, "service")
    ident = rest if rest and prefix in kinds else value
    name = names.get(ident, ident) if kind == "workflow" else ident
    return {"kind": kind, "id": ident, "name": name}


def call_row(r: dict[str, Any], names: dict[str, str], module: dict[str, Any] | None) -> dict[str, Any]:
    subject = _identity(r["sub"], SUBJECT_KINDS, names)
    workflow_id = subject["id"] if subject["kind"] == "workflow" else ""
    approval: dict[str, Any] = {"kind": "person" if r["approvers"] else "none"}
    if r["approval_token_id"]:
        approval["tokenId"] = r["approval_token_id"]
    row: dict[str, Any] = {
        "id": r["id"],
        "at": r["created_at"],
        "gateway": "data",
        "workflowId": workflow_id,
        "workflowName": subject["name"] if workflow_id else "",
        "agentSlug": "",
        "agentName": "",
        "runId": r["thread_id"] or "",
        "target": r["tool"],
        "system": module["system"] if module else "",
        "operation": r["access"] if r["access"] in ("read", "write") else "read",
        "approval": approval,
        "status": STATUS.get(r["outcome"], "error"),
        "latencyMs": r["latency_ms"] or 0,
        "subject": subject,
        "decision": r["decision"],
    }
    if r["act"]:
        actor = _identity(r["act"], ACTOR_KINDS, names)
        row["actor"] = actor
        if actor["kind"] == "agent":
            row["agentSlug"] = row["agentName"] = actor["id"]
        if actor["kind"] == "workflow" and not workflow_id and actor["id"] != "graph":
            row["workflowId"], row["workflowName"] = actor["id"], actor["name"]
    if r["step"]:
        row["step"] = r["step"]
    if r["approval_token_id"]:
        row["approvalTokenId"] = r["approval_token_id"]
    if r["decision"] == "deny" and r["reasons"]:
        row["denyReason"] = "; ".join(r["reasons"])
    if r.get("replay_of"):
        row["replayOf"] = r["replay_of"]
    error = r.get("error")
    if r["outcome"] == "error" and isinstance(error, dict):
        # Which side the call broke on and why, as the executor named it; the message names the host, never an
        # address or a header value.
        failed = cast(dict[str, Any], error)
        row["errorCode"] = str(failed.get("code") or "")
        row["errorMessage"] = str(failed.get("message") or "")
        if failed.get("side") in ("ours", "upstream"):
            row["failureSide"] = failed["side"]
    return row
