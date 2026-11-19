"""Gateway call rows as the console's ToolCallRow (apps/console/src/lib/types/governance.ts), with the identity
fields agreed with the console: `subject` from the call's `sub` (the verified calling service), `actor` from its
`act`, the run, the step, the approval token's fingerprint, the decision and the deny reason. The workflow a call ran
for comes from the subject when it is one, else from the actor."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from ..store.calls import GatewayCall
from ..store.modules import ModuleColumns
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


class CallIdentityJson(TypedDict):
    kind: str
    id: str
    name: str


class CallApprovalJson(TypedDict):
    kind: str
    tokenId: NotRequired[str]
    by: NotRequired[str]


class CallRunAsJson(TypedDict):
    kind: str
    email: NotRequired[str | None]


class CallRowJson(TypedDict):
    """The JSON of one call-log row, keys as `ToolCallRow` names them (modules/schemas.py)."""

    id: str
    at: str
    gateway: str
    workflowId: str
    workflowName: str
    agentSlug: str
    agentName: str
    runId: str
    target: str
    system: str
    title: str
    app: str
    operation: str
    approval: CallApprovalJson
    status: str
    latencyMs: int
    subject: CallIdentityJson
    decision: str
    outcome: str
    effect: bool
    # Set after the literal, in every row: only the key order puts it after `credential`.
    runAs: NotRequired[CallRunAsJson]
    actor: NotRequired[CallIdentityJson]
    step: NotRequired[str]
    approvalTokenId: NotRequired[str]
    denyReason: NotRequired[str]
    replayOf: NotRequired[str]
    environment: NotRequired[str]
    connectionId: NotRequired[str]
    channel: NotRequired[str]
    clientName: NotRequired[str]
    clientId: NotRequired[str]
    actingFor: NotRequired[str]
    credential: NotRequired[str]
    errorCode: NotRequired[str]
    errorMessage: NotRequired[str]
    failureSide: NotRequired[str]


class DayJson(TypedDict):
    """One UTC day of a module's calls (store/calls.DayStats by alias)."""

    date: str
    count: int
    errors: int
    p95Ms: int


class ModuleActivityJson(TypedDict):
    days: list[DayJson]
    denied24h: int
    recent: list[CallRowJson]


def _identity(value: str, kinds: dict[str, str], names: dict[str, str]) -> CallIdentityJson:
    """`kind:id` principals name their kind; anything else is a service. Workflows show the name their approval
    recorded, or their id."""
    prefix, _, rest = value.partition(":")
    kind = kinds.get(prefix, "service")
    ident = rest if rest and prefix in kinds else value
    name = names.get(ident, ident) if kind == "workflow" else ident
    return CallIdentityJson(kind=kind, id=ident, name=name)


def call_row(
    r: GatewayCall, names: dict[str, str], module: ModuleColumns | None, title: str | None = None
) -> CallRowJson:
    """One call as the log shows it. `title` is the tool's display name (a plugin's manifest gives it); the row
    falls back to the tool's own name, so no reader shows a blank."""
    subject = _identity(r.sub, SUBJECT_KINDS, names)
    if r.caller_name:
        # The name the person or key had when the call was made; older rows keep showing the id.
        subject = CallIdentityJson(kind=subject["kind"], id=subject["id"], name=str(r.caller_name))
    workflow_id = subject["id"] if subject["kind"] == "workflow" else ""
    approval: CallApprovalJson = {"kind": "person" if r.approvers else "none"}
    if r.approval_token_id:
        approval["tokenId"] = r.approval_token_id
    if r.approvers:
        # The people the approval token names, so the log says who let the write through, not only that someone did.
        approval["by"] = ", ".join(str(a) for a in r.approvers)
    row: CallRowJson = {
        "id": r.id,
        "at": r.created_at,
        "gateway": "data",
        "workflowId": workflow_id,
        "workflowName": subject["name"] if workflow_id else "",
        "agentSlug": "",
        "agentName": "",
        "runId": r.thread_id or "",
        "target": r.tool,
        "system": module["system"] if module else "",
        "title": title or name_in_words(str(r.tool).rsplit(".", 1)[-1]),
        "app": module["display_name"] if module else "",
        "operation": r.access if r.access in ("read", "write") else "read",
        "approval": approval,
        "status": STATUS.get(r.outcome, "error"),
        "latencyMs": r.latency_ms or 0,
        "subject": subject,
        "decision": r.decision,
        # The log's own outcome, unmapped: `status` shows a call still running as ok, which a workflow reconciling a
        # write by its key must not read as done.
        "outcome": r.outcome,
        # True on the one row whose call carries the write's side effect (a claim); a workflow reconciles on it.
        "effect": bool(r.effect),
    }
    if r.act:
        actor = _identity(r.act, ACTOR_KINDS, names)
        row["actor"] = actor
        if actor["kind"] == "agent":
            row["agentSlug"] = row["agentName"] = actor["id"]
        if actor["kind"] == "workflow" and not workflow_id and actor["id"] != "graph":
            row["workflowId"], row["workflowName"] = actor["id"], actor["name"]
    if r.step:
        row["step"] = r.step
    if r.approval_token_id:
        row["approvalTokenId"] = r.approval_token_id
    if r.decision == "deny" and r.reasons:
        row["denyReason"] = "; ".join(str(x) for x in r.reasons)
    if r.replay_of:
        row["replayOf"] = r.replay_of
    # The kind of run the call was made in and the connection that signed it in: every row shows Test or Live.
    if r.environment:
        row["environment"] = r.environment
    if r.connection_id:
        row["connectionId"] = r.connection_id
    if r.channel:
        row["channel"] = r.channel
    if r.client_name:
        row["clientName"] = r.client_name
    # The assistant a person allowed by name when they signed in (platform-service's client id).
    if r.client_id:
        row["clientId"] = r.client_id
    # Whom the call acted for and whose sign-in signed it.
    if r.acting_for:
        row["actingFor"] = r.acting_for
    if r.credential:
        row["credential"] = r.credential
    # Whom Usage says the call ran as: whose sign-in signed it; one refused before any sign-in ran as the
    # person it acted for, if any. Never the service that carried the call.
    as_person = r.acting_for and r.credential in ("person", None)
    row["runAs"] = {"kind": "person", "email": r.acting_for} if as_person else {"kind": "team"}
    failed = r.error
    if r.outcome == "error" and failed is not None:
        # Which side the call broke on and why, as the executor named it; the message names the host, never an
        # address or a header value.
        row["errorCode"] = str(failed.get("code") or "")
        row["errorMessage"] = str(failed.get("message") or "")
        side = failed.get("side")
        if isinstance(side, str) and side in ("ours", "upstream"):
            row["failureSide"] = side
    return row
