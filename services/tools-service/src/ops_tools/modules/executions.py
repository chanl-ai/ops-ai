"""Gateway call rows as the console's ToolCallRow (apps/console/src/lib/types/governance.ts), with the identity
fields agreed with the console: `subject` from the call's `sub` (the verified calling service), `actor` from its
`act`, the run, the step, the approval token's fingerprint, the decision and the deny reason. The workflow a call ran
for comes from the subject when it is one, else from the actor."""

from __future__ import annotations

from typing import Any, cast

from .seed import name_in_words

# A replay ran nothing, so it is its own status, not a success; a write refused because the same one was running is a
# denial. Both stay out of a module's call counts (CallLog.traffic) and the 409 counts as denied. A write still running
# is running, never ok: whether it happened is not known yet.
STATUS = {
    "ok": "ok",
    "replayed": "replayed",
    "error": "error",
    "refused": "denied",
    "in_progress": "denied",
    "running": "running",
    "lost": "error",
    "abandoned": "denied",
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


def call_row(
    r: dict[str, Any], names: dict[str, str], module: dict[str, Any] | None, title: str | None = None
) -> dict[str, Any]:
    """One call as the log shows it. `title` is the tool's display name (a plugin's manifest gives it); the row
    falls back to the tool's own name, so no reader shows a blank."""
    subject = _identity(r["sub"], SUBJECT_KINDS, names)
    if r.get("caller_name"):
        # The name the person or key had when the call was made; older rows keep showing the id.
        subject = {**subject, "name": str(r["caller_name"])}
    workflow_id = subject["id"] if subject["kind"] == "workflow" else ""
    approval: dict[str, Any] = {"kind": "person" if r["approvers"] else "none"}
    if r["approval_token_id"]:
        approval["tokenId"] = r["approval_token_id"]
    if r["approvers"]:
        # The people the approval token names, so the log says who let the write through, not only that someone did.
        approval["by"] = ", ".join(str(a) for a in r["approvers"])
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
        "title": title or name_in_words(str(r["tool"]).rsplit(".", 1)[-1]),
        "app": module["display_name"] if module else "",
        "operation": r["access"] if r["access"] in ("read", "write") else "read",
        "approval": approval,
        "status": STATUS.get(r["outcome"], "error"),
        "latencyMs": r["latency_ms"] or 0,
        "subject": subject,
        "decision": r["decision"],
        # The log's own outcome, unmapped: `status` shows a call still running as ok, which a workflow reconciling a
        # write by its key must not read as done.
        "outcome": r["outcome"],
        # True on the one row whose call carries the write's side effect (a claim); a workflow reconciles on it.
        "effect": bool(r["effect"]),
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
    # The kind of run the call was made in and the connection that signed it in: every row shows Test or Live.
    if r.get("environment"):
        row["environment"] = r["environment"]
    if r.get("connection_id"):
        row["connectionId"] = r["connection_id"]
    if r.get("channel"):
        row["channel"] = r["channel"]
    if r.get("client_name"):
        row["clientName"] = r["client_name"]
    # The assistant a person allowed by name when they signed in (platform-service's client id).
    if r.get("client_id"):
        row["clientId"] = r["client_id"]
    # Whom the call acted for and whose sign-in signed it.
    if r.get("acting_for"):
        row["actingFor"] = r["acting_for"]
    if r.get("credential"):
        row["credential"] = r["credential"]
    # Whom Usage says the call ran as: whose sign-in signed it; one refused before any sign-in ran as the
    # person it acted for, if any. Never the service that carried the call.
    as_person = r.get("acting_for") and r.get("credential") in ("person", None)
    row["runAs"] = {"kind": "person", "email": r["acting_for"]} if as_person else {"kind": "team"}
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
