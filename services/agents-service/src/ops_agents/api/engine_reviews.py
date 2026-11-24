"""Workflow runner reviews in the Reviews facade (hitl_facade), beside v1 thread reviews and publish requests.

A v2 run waiting on a human review step is listed as a `Review` whose id is the run id; deciding it writes a resume
work row (deduplicated per run, node and iteration) that a worker picks up. Nothing here touches graph_threads or a
v1 graph: v1 reviews are listed exactly as before, and with no engine run waiting this adds nothing to the list.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, NotRequired, TypedDict, cast

from ops_engine.store import RUN_PREFIX, DefinitionRow, DefinitionStore, RunStore
from ops_policy import input_hash
from ops_service_kit.errors import Conflict, Forbidden, NotFound, ValidationFailed
from ops_service_kit.http import Json, JsonList, JsonValue
from ops_service_kit.logging import get_logger
from ops_service_kit.narrow import an_object, entries, json_list, json_object
from ops_store.documents import stored

from ..store.cases import CaseNotFound, CaseStore
from ..store.engine import DatabaseError, EngineTransactions
from ..store.events import EventLog
from ..store.reviews import ReviewStore
from ..store.tenancy import current_team
from .acting_for import person_of
from .auth import (
    Principal,
    require_not_own,
    require_reviews_decide,
    require_step_up,
    require_team_account_use,
    review_teams,
    teams_holding,
    workspace_step_up,
)
from .deps import Runtime
from .engine_resume import enqueue_resume, resumed
from .engine_runs import starters_of
from .legacy_tasks import NOT_READ, legacy_task
from .option_inputs import held_calls
from .review_sla import sla_hours
from .review_text import describe_call, question, requester, source_file
from .task_type_seeds import task_type_store
from .task_view import TaskReads, typed_task
from .team_names import deciding_team
from .tool_access import WritePolicy, policy_of

if TYPE_CHECKING:
    from .agent_registry import ReviewPolicy
    from .hitl_facade import Listed

log = get_logger("ops_agents.api.engine_reviews")


# The stored shapes below are read with `ops_store.documents.stored`, which keeps keys they do not name, so a `waiting`
# document read, changed and written back keeps what it held. Runs waiting now were paused by earlier releases, so
# every key is optional and holds any JSON: a value of another type reads as the views read it (often as nothing)
# instead of refusing the task, which would hide it from the Reviews list.


class ProposedCall(TypedDict, total=False):
    """A write a review step approves (ops_engine compiler.write_call): its operation, its input (the workflow's data)
    and the step key its approval binds to."""

    tool: JsonValue
    input: JsonValue
    step: JsonValue


class ReviewOption(TypedDict, total=False):
    """One choice a review step offers (compiler.review_open): its name and label, and the write it approves with the
    inputs an approver may change."""

    name: JsonValue
    label: JsonValue
    call: JsonValue
    inputs: JsonValue


class ReviewPayload(TypedDict, total=False):
    """What a paused step waits with: a review (compiler.review_open) or a wait for outside work such as a person
    connecting an account (compiler's external wait). `draft`, `params` and `editable.value` are the workflow's own
    data."""

    kind: JsonValue
    node: JsonValue
    review_id: JsonValue
    step_id: JsonValue
    iteration: JsonValue
    title: JsonValue
    draft: JsonValue
    openedAt: JsonValue
    onTimeout: JsonValue
    slaHours: JsonValue
    remindEveryHours: JsonValue
    notDecidedBy: JsonValue
    requestedBy: JsonValue
    editable: JsonValue
    call: JsonValue
    taskType: JsonValue
    params: JsonValue
    options: JsonValue
    event: JsonValue
    key: JsonValue
    app: JsonValue
    connectionId: JsonValue
    appId: JsonValue
    teamAccount: JsonValue
    timeoutSeconds: JsonValue
    resume: JsonValue


class Waiting(TypedDict, total=False):
    """A waiting run's `waiting` column (ops_engine worker._waiting): the paused node and pass, the interrupt and the
    step's payload."""

    node: JsonValue
    iteration: JsonValue
    interruptId: JsonValue
    payload: JsonValue


class Decision(TypedDict, total=False):
    """What a decision resumes the step with (its resume work row's `resume`), as `decide` and `run_as_team_account`
    write it and compiler.review_open reads it."""

    decision: JsonValue
    option: JsonValue
    confirmed: JsonValue
    inputs: JsonValue
    reason: JsonValue
    by: JsonValue
    edited: JsonValue
    call: JsonValue
    approval: Approval | JsonValue
    teamAccount: JsonValue
    event: JsonValue


class ResumeRow(TypedDict, total=False):
    """A resume work row's payload (engine_resume.enqueue_resume): the decision, the step's payload it decided, when,
    and the interrupt it answered."""

    resume: JsonValue
    payload: JsonValue
    at: JsonValue
    interruptId: JsonValue


WAITING = stored(Waiting)
PAYLOAD = stored(ReviewPayload)
OPTION = stored(ReviewOption)
CALL = stored(ProposedCall)
DECISION = stored(Decision)
RESUME_ROW = stored(ResumeRow)


class Approval(TypedDict):
    """The recorded approvals a decision rests on; the worker mints the call's token from them."""

    step: str
    tool: str
    inputHash: str
    approvers: list[str]


class ConnectWait(TypedDict):
    """The app a paused step waits for a person to connect."""

    app: str
    connectionId: JsonValue
    appId: JsonValue
    teamAccount: bool


class ConnectView(ConnectWait):
    """A connect wait with the person whose account it waits for."""

    person: str | None


class Deadline(TypedDict):
    sla: str
    onTimeout: str
    dueAt: str | None
    minutes: int | None


class TypedFields(TypedDict):
    customer: str
    amount: float | None
    currency: str | None
    proposal: str


class Citation(TypedDict):
    page: JsonValue
    quote: JsonValue


class ReadField(TypedDict):
    """One extracted field of a record as a person checks it."""

    value: JsonValue
    extractedValue: JsonValue
    confidence: float | None
    needsReview: bool
    citation: Citation | None
    boxes: JsonList
    bySource: NotRequired[Json]
    conflict: NotRequired[bool]


class ReadRecord(TypedDict):
    values: Json
    fields: dict[str, ReadField]


class SchemaField(TypedDict):
    key: str
    label: str
    type: str
    required: bool
    keyField: bool


class ReadView(TypedDict):
    """An Extract from file result as people read it (read_view)."""

    fileId: str
    fileName: str | None
    floor: float | None
    schema: list[SchemaField]
    records: list[ReadRecord]
    sources: list[str]
    editable: bool
    corrected: list[Json] | None
    # Why no model reply answered the read (cut_off, empty, declined, filtered); None for a read that was answered.
    notRead: str | None


class ReplyCase(TypedDict):
    runId: str
    caseId: str | None
    subject: str | None


class ReplyPreview(TypedDict):
    to: str
    mailbox: str | None
    subject: str
    body: str
    cases: list[ReplyCase]


class OptionView(TypedDict):
    """One option of a review as the console draws it, in reply order."""

    name: str
    label: str
    consequence: str | None
    fields: list[dict[str, str]]
    inputs: JsonList


class EngineRow(TypedDict):
    """A review step as all_rows lists it, in reply order: what a list counts, filters, facets and pages on, and under
    BUILD what expand builds its full review from (the run, its decision or None, and its case, "" for none)."""

    id: str
    title: str
    workflowId: JsonValue
    agentSlug: JsonValue
    kind: str
    risk: str
    status: str
    slaMinutes: int | None
    dueAt: str | None
    createdAt: JsonValue
    caseId: str | None
    _engine_review: tuple[Json, Json | None, str]
    decidedAt: NotRequired[JsonValue]
    assignee: NotRequired[JsonValue]
    caseTitle: NotRequired[str | None]
    canDecide: NotRequired[bool]


class EngineReview(TypedDict):
    """A review step of a run as the console's `Review` (view), in reply order: the keys every view sets, then what
    a typed task, a described call, a read, a reply or a decision add, then who it is assigned to (expand,
    hitl_facade.with_assignee) and whether the caller may decide it (the routes)."""

    origin: Json
    id: str
    title: str
    workflowId: JsonValue
    workflowName: str
    stepName: str | None
    runId: str
    workflowVersion: JsonValue
    agentSlug: JsonValue
    kind: str
    connect: ConnectView | None
    risk: str
    confidence: float | None
    actionTool: str
    policy: ReviewPolicy
    slaMinutes: int | None
    dueAt: str | None
    approvals: list[str]
    status: str
    createdAt: JsonValue
    reasoning: list[str]
    evidence: list[dict[str, str]]
    stepUp: bool
    options: list[OptionView] | None
    optionsError: str | None
    calls: Json | None
    error: JsonValue
    caseId: str | None
    decidingTeam: dict[str, str | None] | None
    customer: str
    amount: float | None
    currency: str | None
    proposal: str
    task: NotRequired[Json]
    consequence: NotRequired[str | None]
    actionFields: NotRequired[list[dict[str, str]]]
    sourceFile: NotRequired[str | None]
    question: NotRequired[str]
    read: NotRequired[ReadView]
    reply: NotRequired[ReplyPreview]
    decidedAt: NotRequired[JsonValue]
    decisionReason: NotRequired[JsonValue]
    option: NotRequired[JsonValue]
    decidedBy: NotRequired[JsonValue]
    resume: NotRequired[Decision]
    stepUpRef: NotRequired[None]
    assignee: NotRequired[JsonValue]
    caseTitle: NotRequired[str | None]
    canDecide: NotRequired[bool]


class Titles(TypedDict):
    """The run's workflow by its display name and each step by its own (titles_of); a list adds `live`, the version
    now serving the workflow (None for none), for a review older than typed steps (legacy_tasks)."""

    workflow: str
    steps: dict[str, str]
    live: NotRequired[DefinitionRow | None]


# The key of an all_rows row that holds what expand builds its full review from; expand drops it with the row.
BUILD: Final = "_engine_review"

# The default options' decisions, as the console sends them, and the ports they choose.
DEFAULT_DECISIONS = {"approved": "approve", "rejected": "reject", "approve": "approve", "reject": "reject"}


# The event a run waiting for a person's own account of an app waits on (ops_engine compiler.connect_wait; reported by
# tools-service connections/account_events.py when they connect).
CONNECTED = "app_account.connected"
CONNECT_KIND = "connect_account"


def connect_wait(payload: ReviewPayload) -> ConnectWait | None:
    """The app a paused step waits for a person to connect, from its park; None for any other pause."""
    if payload.get("kind") != "external" or payload.get("event") != CONNECTED:
        return None
    return {
        "app": str(payload.get("app") or ""),
        "connectionId": payload.get("connectionId"),
        "appId": payload.get("appId"),
        "teamAccount": bool(payload.get("teamAccount")),
    }


async def _connect_view(rt: Runtime, run: Json, payload: ReviewPayload) -> ConnectView | None:
    """A connect wait as the task shows it: the app, and the person whose account it waits for (the run's starter)."""
    wait = connect_wait(payload)
    if wait is None:
        return None
    above = await starters_of(_runs(rt), str(run.get("created_by") or ""), cast(str | None, run.get("team_id")))
    person = person_of(above[-1].created_by if above else run.get("created_by"))
    return {
        "app": wait["app"],
        "connectionId": wait["connectionId"],
        "appId": wait["appId"],
        "teamAccount": wait["teamAccount"],
        "person": person,
    }


def is_engine_id(review_id: str) -> bool:
    return review_id.startswith(RUN_PREFIX)


def _runs(rt: Runtime) -> RunStore:
    return RunStore(EngineTransactions(rt.db))


async def _visible(rt: Runtime, run_id: str) -> Json:
    """The run behind a review, if the selected team may see it (routers/engine.visible_run); else not found."""
    from .routers.engine import visible_run  # noqa: PLC0415 - the router imports the Reviews facade's neighbours

    try:
        # The Reviews views below still read the run as its stored mapping.
        return (await visible_run(rt, run_id)).model_dump()
    except NotFound as e:
        raise NotFound("Review") from e


def _options(payload: ReviewPayload) -> list[str]:
    # `entries` iterates as `payload.get("options") or []` did, so a number there still fails the decision.
    return [str(o.get("name") if isinstance(o, dict) else o) for o in entries(payload.get("options"))]


def step_id(run: Json, payload: ReviewPayload) -> str:
    """A v2 review's id: its step (run:node:iteration), so two review steps of one run are two reviews."""
    return str(payload.get("step_id") or run["id"])


def run_of(review_id: str) -> str:
    return review_id.split(":", 1)[0]


def _listed_options(payload: ReviewPayload) -> list[ReviewOption]:
    """The step's declared options, skipping any entry that is not an object."""
    return [OPTION(o) for o in entries(payload.get("options")) if isinstance(o, dict)]


def _stored_calls(payload: ReviewPayload) -> list[Json]:
    """The step's call and each option's, as the payload holds them (the same objects, so a caller can tell which
    option a call is)."""
    found = [payload.get("call"), *(o.get("call") for o in _listed_options(payload))]
    return [c for c in found if isinstance(c, dict)]


def _calls(payload: ReviewPayload) -> list[ProposedCall]:
    return [CALL(c) for c in _stored_calls(payload)]


def _number(value: object) -> float | None:
    try:
        return float(cast(Any, value)) if value not in (None, "") and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def typed_fields(draft: object, calls: list[ProposedCall]) -> TypedFields:
    """What a review row shows from its step's summary and proposed calls, for any workflow: the customer (the summary's
    matched customer, else its record's name), the amount the first call would act on, that call's account currency
    (none when no account was read), and the proposal as one readable line instead of the summary's raw dict."""
    d = json_object(draft)
    customer, record = d.get("customer"), d.get("record")
    found = json_object(customer)
    read = json_object(record)
    name = found.get("name") or (customer if isinstance(customer, str) else None) or read.get("name")
    first: ProposedCall = calls[0] if calls else {}
    args = an_object(first.get("input") or {}, "the call's input")
    amount = _number(args.get("amount"))
    if amount is None:
        amount = _number(read.get("amount"))
    accounts = [json_object(a) for a in entries(d.get("accounts")) if isinstance(a, dict)]
    account = next((a for a in accounts if a.get("id") == args.get("account_id")), accounts[0] if accounts else {})
    if tool := first.get("tool"):
        proposal = f"{tool}: " + ", ".join(f"{k} {v}" for k, v in args.items())
    else:
        proposal = draft if isinstance(draft, str) else "" if draft is None else json.dumps(draft, default=str)
    return {
        "customer": str(name or ""),
        "amount": amount,
        "currency": str(account["currency"]) if account.get("currency") else None,
        "proposal": proposal,
    }


def _read_in(draft: object) -> Json | None:
    """The Extract from file result a review's summary holds (a value with its file, field schema and records or
    fields), whatever key the workflow gave it; None when the summary is not an object."""
    for value in json_object(draft).values():
        if is_read(value):
            return json_object(value)
    return None


def _combined_in(draft: object) -> Json | None:
    """A Combine facts result the summary holds (its values, the source each came from, and the fields the sources
    disagree on), whatever key the workflow gave it; None when the summary is not an object."""
    for value in json_object(draft).values():
        if (
            isinstance(value, dict)
            and isinstance(value.get("sources"), dict)
            and isinstance(value.get("conflicts"), list)
            and "values" in value
        ):
            return value
    return None


def _plain(value: JsonValue) -> JsonValue:
    """A source's value as a person reads it: an extracted field's `value`, anything else as it is."""
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _by_source(record: ReadRecord, combined: Json) -> list[str]:
    """Marks each field of a one-record read with every source's value and whether they disagree; returns the sources
    in the order they first appear. A field the sources agree on shows the value of the source it was taken from."""
    picked = json_object(combined.get("sources") or {})
    values = combined.get("values") or {}
    disputed: dict[str, list[Json]] = {}
    for c in entries(combined.get("conflicts")):
        if isinstance(c, dict):
            disputed[str(c.get("field"))] = [x for x in entries(c.get("values")) if isinstance(x, dict)]
    names: list[str] = []
    for key, field in record["fields"].items():
        seen = {str(x.get("source")): _plain(x.get("value")) for x in disputed.get(key, [])}
        if not seen and key in picked:
            # Read only here, as `.get` was: values that are not an object fail the read when a field reaches them.
            seen = {str(picked[key]): _plain(an_object(values, "the combined values").get(key))}
        if seen:
            field["bySource"] = seen
            field["conflict"] = key in disputed
            names.extend(n for n in seen if n not in names)
    return names


def _field(scored: JsonValue) -> ReadField:
    s = json_object(scored)
    cited = s.get("citation") or {}
    # A citation that is not an object failed `.get` before; it still fails here.
    page, quote = (an_object(cited, "a field's citation").get(k) for k in ("page", "quote"))
    return {
        "value": s.get("value"),
        "extractedValue": s.get("extractedValue"),
        "confidence": _number(s.get("confidence")),
        "needsReview": bool(s.get("needsReview")),
        "citation": {"page": page, "quote": quote} if cited else None,
        "boxes": [b for b in entries(s.get("boxes")) if isinstance(b, dict) and _is_box(b)],
    }


class TaskWords(TypedDict, total=False):
    """What a typed review's list row takes from its task."""

    title: str
    reasoning: list[str]
    customer: str


def _task_words(task: Json, payload: ReviewPayload) -> TaskWords:
    """A typed review's row words from its task: the header's title and the message as the reason, and whoever the step
    names as having asked, so a list row reads as the task screen does whatever the workflow."""
    data = {str(r["region"]): cast(Json, r.get("data") or {}) for r in cast(list[Json], task["regions"])}
    words: TaskWords = {}
    if title := data.get("header", {}).get("title"):
        words["title"] = str(title)
    if text := data.get("message", {}).get("text"):
        words["reasoning"] = [str(text)]
    if asked := [str(x) for x in entries(payload.get("requestedBy")) if x]:
        words["customer"] = f"Requested by {', '.join(requester(a) for a in asked)}"
    return words


def _is_box(b: Json) -> bool:
    """A box the console can place: a page and four fractions. Anything else from the read is left out."""
    return isinstance(b.get("page"), int) and all(isinstance(b.get(k), (int, float)) for k in ("x", "y", "w", "h"))


def read_view(read: Json, file_name: str | None, edited: JsonValue) -> ReadView:
    """An Extract from file result as people read it, wherever it is shown (Human Tasks, a run's page): the file, the
    floor, each field's label, and per record each field's value, confidence and page quote, with the corrected values a
    person approved it with (`edited`, the whole records list) or None. Nothing takes a correction here; the caller says
    whether its step does (`editable`)."""
    rows: JsonList = []
    if "records" in read:
        rows = list(entries(read.get("records")))
    elif isinstance(fields := read.get("fields"), dict):
        # A one-record read: its fields as one record, with the values the next step reads.
        values: Json = {k: an_object(f, f"field {k}").get("value") for k, f in fields.items()}
        rows = [{"values": values, "fields": fields}]
    records: list[ReadRecord] = []
    for row in rows:
        r = json_object(row)
        scored = an_object(r.get("fields") or {}, "a record's fields")
        records.append(
            {
                # dict() as before: it also takes a list of pairs, and refuses what it refused.
                "values": dict(cast(Json, r.get("values") or {})),
                "fields": {str(k): _field(v) for k, v in scored.items()},
            }
        )
    return {
        "fileId": str(read["fileId"]),
        "fileName": file_name or None,
        "floor": _number(read.get("floor")),
        "schema": [
            {
                "key": str(f.get("key")),
                "label": str(f.get("label") or f.get("key")),
                "type": str(f.get("type") or "text"),
                "required": bool(f.get("required")),
                "keyField": f.get("keyField") is True,
            }
            for f in (x for x in entries(read.get("schema")) if isinstance(x, dict))
        ],
        "records": records,
        "sources": [],
        "editable": False,
        "corrected": [dict(cast(Json, an_object(r, "a corrected record").get("values") or {})) for r in edited]
        if isinstance(edited, list)
        else None,
        "notRead": str(json_object(read.get("incomplete")).get("reason") or "") or None,
    }


def is_read(value: object) -> bool:
    """Whether a value is an Extract from file result: its file, the type's field schema, and records or fields."""
    if not isinstance(value, dict):
        return False
    v = cast(Json, value)
    return "fileId" in v and isinstance(v.get("schema"), list) and ("records" in v or "fields" in v)


def document_read(draft: object, payload: ReviewPayload, resume: Decision | None) -> ReadView | None:
    """A document read as Human Tasks shows it (read_view), with whether the step takes a correction and, for a
    one-record read a Combine facts step weighed, each source's value."""
    read = _read_in(draft)
    if read is None:
        return None
    # Workflows name the file under `document` (the levy flows) or `file` (system extract); either is the file name.
    name = json_object(draft).get("document") or json_object(draft).get("file")
    view = read_view(read, str(name) if isinstance(name, str) and name else None, (resume or {}).get("edited"))
    combined = _combined_in(draft)
    # Several sources side by side only for a one-record read: Combine facts merges one set of fields.
    if combined is not None and len(view["records"]) == 1:
        view["sources"] = _by_source(view["records"][0], combined)
    view["editable"] = isinstance(payload.get("editable"), dict)
    return view


async def reply_preview(rt: Runtime, team: str, draft: object, call: ProposedCall) -> ReplyPreview | None:
    """The reply a review approves (its send_reply call) as it will leave, with the cases the summary's started runs
    are on; a run that has not opened its case yet has none."""
    if call.get("tool") != "send_reply":
        return None
    # `.get` on an input that is not an object failed before; it still fails.
    args = an_object(call.get("input") or {}, "the reply's input")
    summary = json_object(draft)
    started = summary.get("cases")
    listed = entries(started.get("runs")) if isinstance(started, dict) else []
    rows = [r for r in listed if isinstance(r, dict)]
    runs = [r for r in rows if r.get("runId")]
    store = CaseStore(rt.db)
    on_case = await store.cases_of_runs([str(r["runId"]) for r in runs])
    # Each case by its subject, so the reviewer reads who it is about rather than an id; the run's child runs and the
    # cases they opened are in the run's team.
    subjects: dict[str, str] = {}
    for case_id in {c for c in on_case.values() if c}:
        with contextlib.suppress(CaseNotFound):
            subjects[case_id] = (await store.get(case_id, [team])).subject
    return {
        "to": str(args.get("to") or ""),
        "mailbox": str(args["mailbox"]) if args.get("mailbox") else None,
        "subject": str(args.get("subject") or ""),
        "body": str(args.get("body") or ""),
        "cases": [
            {
                "runId": str(r["runId"]),
                "caseId": (c := on_case.get(str(r["runId"]))),
                "subject": subjects.get(c) if c else None,
            }
            for r in runs
        ],
    }


# A not-read read's reason as its task line says it.
NOT_READ_SAID = {
    "cut_off": "the reply was cut off",
    "empty": "the reply held no answer",
    "declined": "the model declined",
    "filtered": "the provider's filter stopped the reply",
}


def _plural(n: int, one: str) -> str:
    return f"{n} {one}{'s' if n != 1 else ''}"


def _read_line(read: ReadView) -> tuple[str, str]:
    """The row's customer and proposal for a document read: who it names and what a person is asked to check, or for
    a read no reply answered, why and how many required fields there are to type."""
    of = f" from {read['fileName']}" if read["fileName"] else ""
    if why := read["notRead"]:
        said = NOT_READ_SAID.get(why, "no reply answered")
        if not read["records"]:
            # A several-records read with no records has no row to type into; approve refuses it (nothing_read).
            return "", f"Nothing read{of}: {said}; it can only be rejected"
        required = sum(1 for f in read["schema"] if f["required"]) * len(read["records"])
        return "", f"Nothing read{of}: {said}; {_plural(required, 'required field')} to type"
    names = [str(r["values"].get("name")) for r in read["records"] if r["values"].get("name")]
    doubtful = sum(1 for r in read["records"] for f in r["fields"].values() if f["needsReview"])
    count = len(read["records"])
    check = f"; {doubtful} field{'s' if doubtful != 1 else ''} to check" if doubtful else ""
    return ", ".join(names), f"Read {count} record{'s' if count != 1 else ''}{of}{check}"


async def titles_of(rt: Runtime, run: Json) -> Titles:
    """The run's workflow by its display name and each step by its own, from the version the run pinned."""
    pinned = await DefinitionStore(EngineTransactions(rt.db)).row(
        str(run["workflow_id"]), cast(int | None, run.get("version"))
    )
    return _titles(run, pinned)


async def titles_by_run(rt: Runtime, runs: list[Json]) -> dict[str, Titles]:
    """titles_of for each run, the versions they pinned read in one query, with the version that now serves each run's
    workflow (`live`, read in one more) for a review older than typed steps (legacy_tasks)."""
    keys = {(str(r["workflow_id"]), int(cast(int, r["version"]))) for r in runs if r.get("version") is not None}
    store = DefinitionStore(EngineTransactions(rt.db))
    pinned = await store.pinned(keys)
    serving = await store.currents({str(r["workflow_id"]) for r in runs})
    out: dict[str, Titles] = {}
    for r in runs:
        titles = _titles(r, pinned.get((str(r["workflow_id"]), int(cast(int, r.get("version") or 0)))))
        titles["live"] = serving.get(str(r["workflow_id"]))
        out[str(r["id"])] = titles
    return out


def _titles(run: Json, row: DefinitionRow | None) -> Titles:
    definition = json_object(row.definition if row else None)
    nodes = [json_object(n) for n in json_list(definition.get("nodes")) if isinstance(n, dict)]
    return {
        "workflow": (row.name if row else "") or str(run["workflow_id"]),
        "steps": {str(n.get("id")): str(n.get("name") or n.get("id")) for n in nodes},
    }


ON_TIMEOUT = {"expire": "Expires: takes the timeout path", "wait": "Stays open, shows overdue"}


def review_deadline(payload: ReviewPayload, workspace_hours: float, now: datetime) -> Deadline:
    """The step's deadline as the row and sheet show it: its own slaHours, else the workspace's review deadline,
    counted from when it opened. A step paused before deadlines were recorded has no openedAt and no countdown."""
    own = payload.get("slaHours")
    # float() as before: a number or a numeric string, and it refuses anything else.
    hours = float(cast(Any, own)) if own is not None else workspace_hours
    sla = f"{hours:g}h" + ("" if own is not None else " (workspace)")
    opened = payload.get("openedAt")
    out: Deadline = {
        "sla": sla,
        "onTimeout": ON_TIMEOUT.get(str(payload.get("onTimeout") or "wait"), ON_TIMEOUT["wait"]),
        "dueAt": None,
        "minutes": None,
    }
    if isinstance(opened, str) and opened:
        due = datetime.fromisoformat(opened.replace("Z", "+00:00")) + timedelta(hours=hours)
        out["dueAt"] = due.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        out["minutes"] = math.floor((due - now).total_seconds() / 60)
    return out


def as_decided(payload: ReviewPayload, resume: Decision) -> ReviewPayload:
    """The paused step's payload with the call its decision sent in place of the one proposed, so a decided review reads
    what was done: an approver who changed an input (a hold's amount) sees that value, as the bank was told.
    A new payload; the stored one is left as it is."""
    sent = resume.get("call")
    if not isinstance(sent, dict):
        return payload
    out = payload.copy()
    if isinstance(payload.get("call"), dict):
        out["call"] = sent
        return out
    chosen = resume.get("option")
    out["options"] = [
        o | {"call": sent} if isinstance(o, dict) and o.get("name") == chosen else o
        for o in entries(payload.get("options"))
    ]
    return out


async def view(
    rt: Runtime,
    run: Json,
    decided: Json | None = None,
    *,
    case_id: str | None = None,
    titles: Titles | None = None,
    reads: TaskReads | None = None,
) -> EngineReview:
    """A review step of a run as a console `Review`: risk and step-up from the operations its options would call,
    as v1's review_view reads them. `case_id` is the case the run is on and `titles` the workflow's and its
    steps' names (titles_of), each looked up when not given; `reads` what a list of typed tasks reads once
    (TaskReads)."""
    if case_id is None:
        case_id = (await CaseStore(rt.db).cases_of_runs([str(run["id"])])).get(str(run["id"]))
    if titles is None:
        titles = await titles_of(rt, run)
    payload = _payload(run, decided)
    options = _options(payload)
    held = _stored_calls(payload)
    calls = [CALL(c) for c in held]
    policies = [await policy_of(rt, str(c.get("tool"))) for c in calls if c.get("tool")]
    two = any(p.approvers > 1 for p in policies)
    step_up = any(p.step_up for p in policies)
    draft = payload.get("draft")
    call: ProposedCall = calls[0] if calls else {}
    deadline: Deadline = review_deadline(payload, await sla_hours(rt), datetime.now(UTC))
    connect = await _connect_view(rt, run, payload)
    if connect is not None:
        # A run waiting for a person to connect has no deadline: the time limit never fails a human wait.
        deadline = deadline.copy()
        deadline["minutes"] = None
        deadline["dueAt"] = None
    typed = typed_fields(draft, calls)
    # Each call in words; typed_fields reads the input named amount as the review's amount, so that input is
    # shown as money in the account's currency.
    money_key = "amount" if typed["amount"] is not None else None
    described = [
        await describe_call(rt, json_object(c), currency=typed["currency"], money_key=money_key) for c in calls
    ]
    declared = _listed_options(payload)
    labels = {str(o.get("name")): str(o.get("label") or str(o.get("name")).capitalize()) for o in declared}
    # By the stored call object: an option's call is the one of `held` it is.
    said = {id(c): d for c, d in zip(held, described, strict=True)}
    inputs_of = {str(o.get("name")): list(entries(o.get("inputs"))) for o in declared}

    def option_view(name: str) -> OptionView:
        opt_call = next((o.get("call") for o in declared if str(o.get("name")) == name), None)
        d = said.get(id(opt_call)) if isinstance(opt_call, dict) else None
        return {
            "name": name,
            "label": labels.get(name, name.capitalize()),
            "consequence": (d["consequence"] or d["sentence"]) if d else None,
            "fields": d["fields"] if d else [],
            # The inputs an approver may change (the hold's amount); without them the console draws no field for it.
            "inputs": inputs_of.get(name, []),
        }

    out: EngineReview = {
        "origin": {"kind": "workflow"},
        "id": step_id(run, payload),
        "title": str(payload.get("title") or f"Review {run['workflow_id']}"),
        "workflowId": run["workflow_id"],
        "workflowName": titles["workflow"],
        # The paused step's own name and its run, so the sheet names "Mailed document · Check the read" and links it.
        "stepName": titles["steps"].get(str(payload.get("node"))),
        "runId": str(run["id"]),
        "workflowVersion": run.get("version"),
        "agentSlug": run["workflow_id"],
        "kind": CONNECT_KIND if connect is not None else "approval",
        "connect": connect,
        "risk": _risk(policies),
        # No model scores a v2 review step: no confidence, not a confidence of zero.
        "confidence": None,
        "actionTool": str(call.get("tool") or ""),
        "policy": {
            "id": f"{run['workflow_id']}:{payload.get('node', 'review')}",
            "name": "Human review",
            "condition": "Every paused step",
            "reviewers": "Reviewers",
            "sla": deadline["sla"],
            "onTimeout": deadline["onTimeout"],
            "fourEyes": two,
        },
        # Minutes left before the deadline, negative once past it; null once decided.
        "slaMinutes": deadline["minutes"] if decided is None else None,
        "dueAt": deadline["dueAt"],
        "approvals": [],
        "status": "pending",
        "createdAt": run["updated_at"],
        "reasoning": [],
        "evidence": [
            {
                "kind": "tool",
                "label": d["label"],
                "detail": "; ".join(f"{f['label']} {f['value']}" for f in d["fields"]),
            }
            for d in described
        ],
        "stepUp": step_up,
        "options": [option_view(o) for o in options] or None,
        "optionsError": None,
        "calls": None,
        "error": None,
        "caseId": case_id or None,
        "decidingTeam": await deciding_team(rt, cast(str | None, run.get("team_id"))),
        "customer": typed["customer"],
        "amount": typed["amount"],
        "currency": typed["currency"],
        "proposal": typed["proposal"],
    }
    if task := await typed_task(rt, json_object(payload), run, reads):
        out["task"] = task
        # Each of these keys is already in `out`, so setting them one by one keeps the reply's key order.
        words = _task_words(task, payload)
        if "title" in words:
            out["title"] = words["title"]
        if "reasoning" in words:
            out["reasoning"] = words["reasoning"]
        if "customer" in words:
            out["customer"] = words["customer"]
        # A typed task's actions say what each choice does; listed under Details they read as things already done.
        out["evidence"] = []
    if described:
        out["proposal"] = described[0]["sentence"]
        # What approving the step's own call does and sends, for a step without options.
        out["consequence"] = described[0]["consequence"]
        out["actionFields"] = described[0]["fields"]
    out["sourceFile"] = source_file(draft, run.get("input"))
    # Asked once the system sheet has named the step ("Let Dispute email use Core banking?").
    out["question"] = question(
        options=[labels.get(o, o.capitalize()) for o in options],
        first=described[0] if described else None,
        customer=typed["customer"],
        title=out["title"],
    )
    decision = DECISION((decided or {}).get("resume") or {})
    read = document_read(draft, payload, decision)
    if read is not None:
        out["customer"], out["proposal"] = _read_line(read)
        out["read"] = read
    if calls and (reply := await reply_preview(rt, str(run["team_id"]), draft, calls[0])) is not None:
        out["reply"] = reply
    if decided is not None:
        resume = decision
        out["status"] = _decided_status(decided)
        out["decidedAt"] = decided.get("at")
        out["decisionReason"] = resume.get("reason")
        out["option"] = resume.get("option")
        out["decidedBy"] = resume.get("by")
        out["resume"] = resume
        out["stepUpRef"] = None
    # A review older than typed steps draws through a task type too, from the words built above.
    if "task" not in out and (
        legacy := await legacy_task(rt, run, json_object(payload), out, live=titles.get("live", NOT_READ), reads=reads)
    ):
        out["task"] = legacy
    return out


async def _decisions(rt: Runtime, run_id: str) -> list[Json]:
    """The run's resume rows' payloads (ResumeRow), oldest first."""
    return [w["payload"] for w in await _runs(rt).work(run_id) if w["kind"] == "resume"]


def _payload(run: Json, decided: Json | ResumeRow | None) -> ReviewPayload:
    """The step's payload as its review reads it: the decided call in place of the proposed one once decided."""
    waiting = WAITING(run.get("waiting") or {})
    payload = PAYLOAD((decided or {}).get("payload") or waiting.get("payload") or {})
    if decided is not None:
        payload = as_decided(payload, DECISION(decided.get("resume") or {}))
    return payload


def _risk(policies: list[WritePolicy]) -> str:
    """A step whose call needs two approvers is high risk, any other write medium, a read low."""
    if any(p.approvers > 1 for p in policies):
        return "high"
    return "medium" if any(p.access == "write" for p in policies) else "low"


async def team_runs(rt: Runtime) -> list[Json]:
    """The team's runs a task list reads, newest first: the newest 200, for the decided tasks they hold, and the
    newest `review_list_rows_per_source` runs waiting for a person, so an open task leaves the list only past that
    many waiting runs (logged as `review_source_capped`)."""
    store = _runs(rt)
    cap = rt.settings.review_list_rows_per_source
    recent = await store.list(team_id=current_team())
    waiting = await store.list(team_id=current_team(), status="waiting", limit=cap)
    if len(waiting) >= cap:
        log.warning("review_source_capped", source="waiting_runs", cap=cap)
    seen = {r.id for r in recent}
    rows = recent + [r for r in waiting if r.id not in seen]
    # The Reviews views read each run as its stored mapping.
    return [r.model_dump() for r in sorted(rows, key=lambda r: r.created_at, reverse=True)]


@dataclass(frozen=True)
class RowReads:
    """What `all_rows` reads from this service's own tables: the runs, the case each is on, and the review steps they
    hold, so a route can ask tools-service about `tools` with nothing open before `build_rows`."""

    on_case: dict[str, str]
    steps: list[tuple[Json, Json | None]]
    payloads: list[ReviewPayload]

    @property
    def tools(self) -> list[str]:
        return sorted({str(c.get("tool")) for p in self.payloads for c in _calls(p) if c.get("tool")})


def tools_of(steps: list[tuple[Json, Json | None]]) -> list[str]:
    """The tools the calls of these review steps (a run and its decision, None for the one it waits on) name."""
    return sorted({str(c.get("tool")) for run, d in steps for c in _calls(_payload(run, d)) if c.get("tool")})


async def ask_policies(rt: Runtime, tools: list[str]) -> None:
    """Each tool's write policy from tools-service, all at once."""
    await asyncio.gather(*(policy_of(rt, t) for t in tools))


async def read_rows(rt: Runtime) -> RowReads | None:
    """The local reads of `all_rows`; None when the database is not yet migrated to the runner's tables."""
    try:
        runs = await team_runs(rt)
    except DatabaseError as e:  # A database not yet migrated to the runner's tables lists v1 reviews alone.
        log.warning("engine_reviews_unavailable", error=type(e).__name__)
        return None
    on_case = await CaseStore(rt.db).cases_of_runs([str(r["id"]) for r in runs])
    decisions = await _runs(rt).resumes([str(r["id"]) for r in runs])
    steps: list[tuple[Json, Json | None]] = []
    for run in runs:
        steps += [(run, d) for d in decisions.get(str(run["id"]), [])]
        if run["status"] == "waiting" and run.get("waiting"):
            steps.append((run, None))
    return RowReads(on_case, steps, [_payload(run, d) for run, d in steps])


async def all_rows(rt: Runtime) -> list[EngineRow]:
    """Each review step of the selected team's runs (the one a run waits on as pending, and every decided one) as a
    row holding what the list counts, filters, facets and pages on: id, status, title, risk, workflow, deadline, case
    and when it opened and was decided. No typed task, wording or reply preview is read; `expand` builds the full
    review for the rows a page shows, so a count reads no more than its rows."""
    return await build_rows(rt, await read_rows(rt))


async def build_rows(rt: Runtime, reads: RowReads | None) -> list[EngineRow]:
    """`all_rows` from its local reads. Every tool the steps call is asked at once; within one_read_per_tool each is
    then asked once for the request, so a caller that asked first (`prefetch_policies`) makes this call none."""
    if reads is None:
        return []
    on_case, steps, payloads = reads.on_case, reads.steps, reads.payloads
    await ask_policies(rt, reads.tools)
    hours = await sla_hours(rt)
    now = datetime.now(UTC)
    out: list[EngineRow] = []
    for (run, decided), payload in zip(steps, payloads, strict=True):
        policies = [await policy_of(rt, str(c.get("tool"))) for c in _calls(payload) if c.get("tool")]
        # A wait for a person to connect their account has no deadline.
        timed = decided is None and connect_wait(payload) is None
        row: EngineRow = {
            "id": step_id(run, payload),
            "title": str(payload.get("title") or f"Review {run['workflow_id']}"),
            "workflowId": run["workflow_id"],
            "agentSlug": run["workflow_id"],
            "kind": CONNECT_KIND if connect_wait(payload) is not None else "approval",
            "risk": _risk(policies),
            "status": "pending" if decided is None else _decided_status(decided),
            "slaMinutes": review_deadline(payload, hours, now)["minutes"] if timed else None,
            # The deadline a list grouped by case orders on; the place reads the same from its own rows.
            "dueAt": review_deadline(payload, hours, now)["dueAt"] if timed else None,
            "createdAt": run["updated_at"],
            # "" says "looked up, on no case", so expand does not ask again per row.
            "caseId": on_case.get(str(run["id"])) or None,
            BUILD: (run, decided, on_case.get(str(run["id"]), "")),
        }
        if decided is not None:
            row["decidedAt"] = decided.get("at")
        out.append(row)
    return out


async def expand(rt: Runtime, rows: list[Listed]) -> list[Listed]:
    """Each row all_rows made, as its full review (who it is assigned to kept); every other row as it is. What the
    rows' typed tasks and titles read is read once for all of them."""
    light = [cast(EngineRow, r) for r in rows if BUILD in r]
    if not light:
        return rows
    runs = list({str(r[BUILD][0]["id"]): r[BUILD][0] for r in light}.values())
    named = await titles_by_run(rt, runs)
    payloads = [_payload(r[BUILD][0], r[BUILD][1]) for r in light]
    reads = TaskReads(rt, runs, [str(p.get("step_id")) for p in payloads if p.get("step_id")])
    built: dict[int, EngineReview] = {}
    for r in light:
        run, decided, case_id = r[BUILD]
        full = await view(rt, run, decided, case_id=case_id, titles=named[str(run["id"])], reads=reads)
        if "assignee" in r:
            full["assignee"] = r["assignee"]
        built[id(r)] = full
    return [built.get(id(r), r) for r in rows]


async def all_places(rt: Runtime) -> list[dict[str, Any]]:
    """all_views' reviews by id and status alone, in its order: a task's place in its queue (hitl_facade.queue_place)
    reads no task type, policy or wording."""
    try:
        runs = await team_runs(rt)
    except DatabaseError as e:
        log.warning("engine_reviews_unavailable", error=type(e).__name__)
        return []
    decisions = await _runs(rt).resumes([str(r["id"]) for r in runs])
    # The case and the deadline a list grouped by case orders on: one query and one setting, no review built.
    on_case = await CaseStore(rt.db).cases_of_runs([str(r["id"]) for r in runs])
    hours = await sla_hours(rt)
    now = datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for run in runs:
        case_id = on_case.get(str(run["id"])) or None
        for d in decisions.get(str(run["id"]), []):
            payload = PAYLOAD(d.get("payload") or {})
            out.append({"id": step_id(run, payload), "status": _decided_status(d), "caseId": case_id, "dueAt": None})
        if run["status"] == "waiting" and run.get("waiting"):
            waiting = PAYLOAD(WAITING(run["waiting"]).get("payload") or {})
            due = review_deadline(waiting, hours, now)["dueAt"]
            out.append({"id": step_id(run, waiting), "status": "pending", "caseId": case_id, "dueAt": due})
    return out


def _decided_status(decided: Json | ResumeRow) -> str:
    resume = DECISION(decided.get("resume") or {})
    approved = resume.get("decision") in ("approved", "approve") and resume.get("option") != "reject"
    return "approved" if approved else "rejected"


async def get(rt: Runtime, review_id: str) -> EngineReview:
    """A review by its step id; a run id names the step the run waits on, else its latest decision."""
    run = await _visible(rt, run_of(review_id))
    waiting = WAITING(run.get("waiting") or {})
    if (
        run["status"] == "waiting"
        and waiting
        and review_id in (run["id"], step_id(run, PAYLOAD(waiting.get("payload") or {})))
    ):
        return await view(rt, run)
    decided = [
        d
        for d in await _decisions(rt, cast(str, run["id"]))
        if review_id in (run["id"], step_id(run, PAYLOAD(RESUME_ROW(d).get("payload") or {})))
    ]
    if decided:
        return await view(rt, run, decided[-1])
    raise NotFound("Review")


async def _check_decider(rt: Runtime, approver: Principal, run: Json, calls: list[Json]) -> None:
    """Who may decide a run's review: a reviewer or admin of the run's team, whatever the writes it decides (`calls`)
    are, and not who started the run or whom the step names in requestedBy while requesterMayDecide is off.
    Anyone the step names in notDecidedBy is refused whatever the policy, such as whoever saved the version it
    approves."""
    del calls
    paused = PAYLOAD(WAITING(run.get("waiting") or {}).get("payload") or {})
    # `entries` iterates as `or []` did: a number in either list still fails the check rather than passing it.
    barred = {str(x).lower() for x in entries(paused.get("notDecidedBy"))}
    if approver.email.lower() in barred:
        raise Forbidden("You are named as not deciding this review; another reviewer must.", code="not_decided_by")
    require_reviews_decide(review_teams(approver), str(run["team_id"]), "this review")
    # Who started the run, and whoever the step names as having asked (an event's requester), under the same policy.
    asked = [cast(str | None, run["created_by"]), *(str(x) for x in entries(paused.get("requestedBy")))]
    require_not_own(approver, asked, team=str(run["team_id"]), what="this run's review")


async def check_decider(rt: Runtime, approver: Principal, review_id: str) -> None:
    """The decision route's checks on a waiting run's review, without deciding it (canDecide)."""
    run = await _visible(rt, run_of(review_id))
    waiting = WAITING(run.get("waiting") or {})
    if not waiting:
        raise Conflict("This run is not waiting for a decision.", code="run_not_waiting")
    await _check_decider(rt, approver, run, held_calls(json_object(PAYLOAD(waiting.get("payload") or {}))))


class Nothing:
    """No correction was sent."""


NOTHING = Nothing()


def _record_keys(row: JsonValue) -> set[str] | None:
    """The field names of one record (`{"values": {...}}`), or None when it is not one."""
    if not isinstance(row, dict):
        return None
    values = row.get("values")
    return {str(k) for k in values} if isinstance(values, dict) else None


def _read_correction(read: Json, edited: JsonValue) -> None:
    """A correction of a whole read: as many records as were read (exactly one for a one-record read), each keeping its
    `values` to the fields of the read's type."""
    if not isinstance(edited, list) or any(_record_keys(r) is None for r in edited):
        raise ValidationFailed("A correction lists the records, each with its values.")
    count = 1 if "fields" in read and "records" not in read else len(entries(read.get("records")))
    if len(edited) != count:
        raise ValidationFailed(f"A correction lists the {_plural(count, 'record')} that were read.")
    allowed = {str(f.get("key")) for f in (x for x in entries(read.get("schema")) if isinstance(x, dict))}
    found: set[str] = set()
    for row in edited:
        found |= _record_keys(row) or set()
    if unknown := sorted(found - allowed):
        raise ValidationFailed(f"A correction names fields the read does not have: {', '.join(unknown)}.")


NOT_EDITABLE = (
    "This version of Extract a file cannot take typed values, so this task can only be rejected. Your admin needs to "
    "approve the extraction update in Reviews; then read the file again."
)


def _refuse_not_editable(paused: ReviewPayload) -> None:
    """An approve of a read no reply answered needs a step that takes typed values; on one that takes none (a version
    of Extract a file from before it did) the task can only be rejected, and says why."""
    if "editable" in paused:
        return
    read = document_read(paused.get("draft"), paused, None)
    if read is not None and read["notRead"] and read["records"]:
        raise ValidationFailed(NOT_EDITABLE, code="not_editable")


def _require_documents_edit(approver: Principal, team: str) -> None:
    """Typed values change a read, which is documents.edit in the run's team: reviews.decide alone changes none."""
    if team not in teams_holding(approver, "documents", "edit"):
        raise Forbidden(
            f"Only someone who edits the documents of {team} changes the values of a read.",
            code="role_required",
            details={"teamId": team, "area": "documents", "action": "edit"},
        )


def correction(paused: ReviewPayload, inputs: Json | None) -> tuple[JsonValue | Nothing, Json | None]:
    """A reviewer's correction (`inputs.edited`) of the step's editable value, checked against it, and the inputs left
    for the option's call. A list of records keeps each record's `values` to the keys the read has; a dict keeps its own
    keys. NOTHING when no correction was sent."""
    rest = dict(inputs or {})
    if "edited" not in rest:
        return NOTHING, inputs
    edited = rest.pop("edited")
    editable = paused.get("editable")
    if not isinstance(editable, dict):
        raise ValidationFailed("This review has nothing to correct.")
    was = editable.get("value")
    if is_read(was):
        # A whole read is corrected as the console shows it: the records list, one record for a one-record read.
        read = cast(Json, was)
        _read_correction(read, edited)
        unknown = []
    elif isinstance(was, list):
        allowed: set[str] = set()
        for row in was:
            allowed |= _record_keys(row) or set()
        if not isinstance(edited, list):
            raise ValidationFailed("A correction lists the records, each with its values.")
        found: set[str] = set()
        for row in edited:
            keys = _record_keys(row)
            if keys is None:
                raise ValidationFailed("A correction lists the records, each with its values.")
            found |= keys
        unknown = sorted(found - allowed)
    elif isinstance(was, dict):
        if not isinstance(edited, dict):
            raise ValidationFailed("A correction has the same fields as what was read.")
        unknown = sorted({str(k) for k in edited} - {str(k) for k in was})
    else:
        raise ValidationFailed("This review's value cannot be corrected.")
    if unknown:
        raise ValidationFailed(f"A correction names fields the read does not have: {', '.join(unknown)}.")
    return edited, rest or None


async def decide(
    rt: Runtime,
    approver: Principal,
    run_id: str,
    *,
    decision: str,
    reason: str | None,
    step_up_token: str | None = None,
    inputs: Json | None = None,
    amount: float | None = None,
) -> EngineReview:
    """Records the decision as the run's resume work row; a repeat of the same decision returns the review, a
    different one is refused. The person who started the run decides its review only while requesterMayDecide is on.

    A decision that approves a write (an option's call, or Approve on a step that `approves` a tool node) follows the
    v1 levy rule (hitl_facade.decide): the reviewer's inputs are validated against the option's declaration, the
    operation's approving team and step-up are checked, and once its policy's number of people have approved, one
    token is minted bound to that call's thread, step, operation and input hash. The tool node sends exactly that
    call with that token; without it the gateway refuses the write."""
    runs = _runs(rt)
    review_id, run_id = run_id, run_of(run_id)
    run = await _visible(rt, run_id)
    waiting: Waiting = WAITING(run.get("waiting") or {})
    if waiting and review_id not in (run_id, step_id(run, PAYLOAD(waiting.get("payload") or {}))):
        waiting = {}  # an earlier review step of this run: answered from its decision below
    if not waiting:
        earlier = await _decisions(rt, run_id)
        if earlier:
            was = DECISION(RESUME_ROW(earlier[-1]).get("resume") or {})
            if decision in (was.get("decision"), was.get("option")):
                return await view(rt, run, earlier[-1])
            raise Conflict(
                f"This review was already decided: {was.get('option') or was.get('decision')}.", code="already_decided"
            )
        raise Conflict("This run is not waiting for a decision.", code="run_not_waiting")
    paused = PAYLOAD(waiting.get("payload") or {})
    if connect_wait(paused) is not None:
        raise Conflict(
            "This run waits for an account: it goes on once its person connects theirs, or runs on the team account.",
            code="connect_wait",
        )
    options = _options(paused)
    # Every option but reject approves, as below; a decision no option names is refused below.
    if (decision != "reject") if options else DEFAULT_DECISIONS.get(decision) == "approve":
        _refuse_not_editable(paused)
    edited, inputs = correction(paused, inputs)
    if not isinstance(edited, Nothing):
        _require_documents_edit(approver, str(run["team_id"]))
    call: Json | None = None
    if options:
        if decision not in options:
            raise ValidationFailed(f"This review is decided with one of: {', '.join(options)}.")
        # The reject option rejects, as Reject does on a step without options; every other option approves its call.
        resume: Decision = {"decision": "rejected" if decision == "reject" else "approved", "option": decision}
        chosen = next((o for o in _listed_options(paused) if o.get("name") == decision), None)
        if chosen is not None and chosen.get("call"):
            from .hitl_facade import option_call  # noqa: PLC0415 - hitl_facade imports this module

            call = option_call(json_object(chosen), inputs, amount)
    else:
        if decision not in DEFAULT_DECISIONS:
            raise ValidationFailed("This review is approved or rejected.")
        resume = {"decision": "approved" if DEFAULT_DECISIONS[decision] == "approve" else "rejected"}
        if resume.get("decision") == "approved" and (proposed := paused.get("call")):
            call = dict(an_object(proposed, "the step's call"))
    if paused.get("taskType"):
        rest = dict(inputs or {})
        confirmed = rest.pop("confirmed", None)
        action = await _typed_action(rt, run, paused, str(resume.get("option") or DEFAULT_DECISIONS[decision]))
        if action.get("requires"):
            _check_requirement(str(action["requires"]), paused, confirmed, edited)
            resume["confirmed"] = confirmed
        if call is None and rest:
            # A typed action's own inputs (a Reject's assignee) travel to the workflow with the decision.
            resume["inputs"] = _action_inputs(action, rest)
    if resume.get("decision") == "approved":
        _required_fields_filled(paused, None, edited)
    # An approval is checked against the call it sends; a rejection against every write the step holds.
    await _check_decider(rt, approver, run, [call] if call is not None else held_calls(json_object(paused)))
    resume["reason"] = reason
    resume["by"] = approver.email
    if not isinstance(edited, Nothing) and resume.get("decision") == "approved":
        resume["edited"] = edited
    if call is not None:
        approval = await _approve_call(
            rt, approver, run_id, call, step_up_token=step_up_token, team_id=str(run["team_id"])
        )
        if approval is None:
            waiting_on_more = await view(rt, run)
            waiting_on_more["status"] = "in_review"
            return waiting_on_more
        # A reference to the recorded approvals, never the token: the worker mints the token from them when it calls
        # the gateway, so no token is stored in the queue, the journal or a run's detail.
        resume["call"] = call
        resume["approval"] = approval
    row, created = await enqueue_resume(rt.db, run_id, dict(waiting), dict(resume))
    if not created:
        was = DECISION(RESUME_ROW(row["payload"]).get("resume") or {})
        if was.get("decision") != resume.get("decision") or was.get("option") != resume.get("option"):
            raise Conflict("This review was already decided.", code="already_decided")
        return await view(rt, run, row["payload"])
    await runs.update(run_id, status="queued", waiting=None)
    await EventLog(rt.db).append(
        thread_id=run_id,
        team_id=cast(str, run["team_id"]),
        run_id=run_id,
        type_="decided",
        # enqueue_resume's key read `node` already, so it is there.
        node=str(waiting.get("node")),
        data={"decision": resume.get("decision"), "option": resume.get("option"), "decidedBy": approver.email},
    )
    cases = CaseStore(rt.db)
    case_id = (await cases.cases_of_runs([run_id])).get(run_id)
    if case_id is not None:
        # The decision is on the case's timeline too: the case reads as the issue's whole history.
        detail = {"decision": resume.get("decision"), "option": resume.get("option"), "reason": reason}
        await cases.add_event(case_id, "decision", ref=step_id(run, paused), detail=detail, by=approver.email)
    return await view(rt, run, row["payload"], case_id=case_id or "")


async def _approve_call(
    rt: Runtime,
    approver: Principal,
    run_id: str,
    call: Json,
    *,
    step_up_token: str | None,
    team_id: str,
) -> Approval | None:
    """Records `approver`'s approval of `call` in the run's team (`team_id`) and returns the approval reference
    ({step, inputHash, approvers}) once as many distinct people as its policy names have approved this exact input;
    None while more are needed."""
    # Indexed as before: a call missing its tool, input or step fails here rather than approving.
    tool = str(call["tool"])
    policy = await policy_of(rt, tool)  # its approving team was checked with the decider (_check_decider)
    if policy.step_up or workspace_step_up(approver):
        require_step_up(rt, approver.email, step_up_token)
    digest = input_hash(call["input"])
    found = await ReviewStore(rt.db).approve(
        run_id, str(call["step"]), approver.email, digest, distinct=policy.approvers > 1, team_id=team_id
    )
    if found is None:
        raise Forbidden("You already approved this; a second, different person has to approve it.")
    if len(found) < policy.approvers:
        return None
    return {"step": str(call["step"]), "tool": tool, "inputHash": digest, "approvers": found}


async def _typed_action(rt: Runtime, run: Json, paused: ReviewPayload, port: str) -> Json:
    """The task type's action that leads to `port`, from the type version the step names in the run's team; empty when
    it has none."""
    ref = an_object(paused.get("taskType"), "the step's taskType")
    types = await task_type_store(rt, str(run["team_id"]))
    _, record = await types.published(str(ref["id"]), cast(int | None, ref.get("version")))
    # Each action is read as an object up to the one that matches, as `.get` on each did.
    actions = (an_object(a, "a task type's action") for a in entries(record.get("actions")))
    none: Json = {}
    return next((a for a in actions if a.get("port") == port), none)


# An action input naming a person (a task type's `format: person`), and the shape that names one.
PERSON = "person"


def _is_email(text: str) -> bool:
    """One "@", a local part and a dotted domain with no whitespace. Plain splits, not a regex, so a long
    hostile string costs linear time."""
    local, at, domain = text.partition("@")
    if not at or "@" in domain or not local or any(c.isspace() for c in text):
        return False
    labels = domain.split(".")
    return len(labels) >= 2 and all(labels)


def _action_inputs(action: Json, inputs: Json) -> Json:
    """The inputs `action` declares, checked: one it does not declare, or a required one left out, is refused naming
    it, so a misspelt assignee never silently leaves the task with the team."""
    declared: dict[str, Json] = {}
    for raw in entries(action.get("inputs")):
        i = an_object(raw, "an action's input")
        declared[str(i["name"])] = i
    if unknown := sorted(set(inputs) - set(declared)):
        raise ValidationFailed(f"This action takes no {', '.join(unknown)}.")
    if missing := sorted(n for n, i in declared.items() if i.get("required") and inputs.get(n) in (None, "")):
        raise ValidationFailed(f"This action needs {', '.join(missing)}.")
    # A person is named by email, as assignments are; empty leaves the task with the team's queue.
    if named := sorted(
        n
        for n, i in declared.items()
        if i.get("format") == PERSON and inputs.get(n) not in (None, "") and not _is_email(str(inputs[n]))
    ):
        raise ValidationFailed(f"{', '.join(named)} names a person by email.")
    return dict(inputs)


def _key_fields_left(paused: ReviewPayload, confirmed: JsonValue) -> int:
    """How many key fields of the step's read are not in `confirmed` (record index to field keys), counted as the
    console's keyFieldsLeft counts them; 0 when the read marks none or there is no read."""
    read = document_read(paused.get("draft"), paused, None)
    if read is None:
        return 0
    # Keyed by the record's index as a string ("0"), or as a number by a caller that built the mapping itself.
    given = cast("dict[object, JsonValue]", confirmed) if isinstance(confirmed, dict) else {}
    keys = [f["key"] for f in read["schema"] if f["keyField"]]
    left = 0
    for i in range(len(read["records"])):
        seen = given.get(str(i), given.get(i))
        done = {str(k) for k in seen} if isinstance(seen, list) else set[str]()
        left += sum(k not in done for k in keys)
    return left


def _key_fields_confirmed(paused: ReviewPayload, confirmed: JsonValue, edited: JsonValue | Nothing) -> None:
    if left := _key_fields_left(paused, confirmed):
        what = "1 key field" if left == 1 else f"{left} key fields"
        raise ValidationFailed(f"Confirm {what} before approving.", code="key_fields_unconfirmed")


def _blank(value: JsonValue) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _typed(value: JsonValue) -> JsonValue:
    """A corrected field's value: a field object's `value`, or the value itself."""
    return cast(Json, value).get("value") if isinstance(value, dict) else value


def _required_fields_filled(paused: ReviewPayload, confirmed: JsonValue, edited: JsonValue | Nothing) -> None:
    """A read no model reply answered is approved only once every required field has a value, typed by the person
    (`inputs.edited`) over what was read; optional fields may stay empty. A several-records read with no records has
    nothing to approve. A read that was answered passes: its empty fields are the model's answer."""
    read = document_read(paused.get("draft"), paused, None)
    if read is None or not read["notRead"]:
        return
    if not read["records"]:
        raise ValidationFailed(
            "Nothing was read from this file, so this task can only be rejected.", code="nothing_read"
        )
    required = [f["key"] for f in read["schema"] if f["required"]]
    rows: list[Json] = [r["values"] for r in read["records"]]
    if isinstance(edited, list):
        rows = [json_object(json_object(r).get("values")) for r in edited]
    elif isinstance(edited, dict):
        rows = [{k: _typed(v) for k, v in edited.items()}]
    if left := sum(_blank(row.get(k)) for row in rows for k in required):
        what = _plural(left, "required field")
        raise ValidationFailed(f"Type {what} before approving.", code="required_fields_empty")


# What a task type's action can wait for (its `requires`), checked on the decision as the console blocks the button,
# so a call that skips the console cannot approve values nobody checked. required_fields_filled also holds every
# approve of a read with no answer, whatever its type names.
Requirement = Callable[[ReviewPayload, JsonValue, JsonValue | Nothing], None]
REQUIREMENTS: dict[str, Requirement] = {
    "key_fields_confirmed": _key_fields_confirmed,
    "required_fields_filled": _required_fields_filled,
}


def _check_requirement(name: str, paused: ReviewPayload, confirmed: JsonValue, edited: JsonValue | Nothing) -> None:
    check = REQUIREMENTS.get(name)
    if check is None:
        # A type naming a rule this service cannot check is refused rather than approved unchecked.
        raise ValidationFailed(
            f"This action waits for {name}, which cannot be checked here.", code="unknown_requirement"
        )
    check(paused, confirmed, edited)


async def run_as_team_account(rt: Runtime, me: Principal, review_id: str) -> EngineReview:
    """Run as the team account: the step waiting for a person's own account goes on with the app's team
    account in its place, for someone the roles grid lets use it, on an app that has one. The run is queued; the view
    of the task is returned as it now stands."""
    run = await _visible(rt, run_of(review_id))
    waiting = WAITING(run.get("waiting") or {})
    paused = PAYLOAD(waiting.get("payload") or {})
    wait = connect_wait(paused)
    if not waiting or wait is None or review_id not in (str(run["id"]), step_id(run, paused)):
        raise Conflict("This run is not waiting for an account.", code="run_not_waiting")
    app = wait["app"] or "This app"
    require_team_account_use(me, team_id=str(run["team_id"]), what=f"{app}'s team account")
    if not wait["teamAccount"]:
        raise Conflict(f"{app} has no team account to run as; its person connects their own.", code="no_team_account")
    resume: Decision = {"teamAccount": {"by": me.email}}
    await resumed(
        rt.db, str(run["id"]), str(run["team_id"]), json_object(dict(waiting)), dict(resume), source="team_account"
    )
    return await view(rt, await _visible(rt, str(run["id"])))
