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
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from ops_engine.store import RUN_PREFIX, DefinitionStore, RunStore, WorkQueue
from ops_policy import input_hash
from ops_service_kit.errors import Conflict, Forbidden, NotFound, ValidationFailed
from ops_service_kit.ids import now_iso
from ops_service_kit.logging import get_logger

from ..store.cases import CaseNotFound, CaseStore
from ..store.engine import DatabaseError, EngineTransactions
from ..store.events import EventLog
from ..store.reviews import ReviewStore
from ..store.tenancy import current_team
from .auth import Principal, require_not_own, require_reviews_decide, require_step_up, review_teams, workspace_step_up
from .deps import Runtime
from .legacy_tasks import NOT_READ, legacy_task
from .option_inputs import held_calls
from .review_sla import sla_hours
from .review_text import describe_call, question, source_file
from .task_type_seeds import task_type_store
from .task_view import TaskReads, typed_task
from .team_names import deciding_team
from .tool_access import WritePolicy, policy_of

log = get_logger("ops_agents.api.engine_reviews")

# The key of an all_rows row that holds what expand builds its full review from; expand drops it with the row.
BUILD = "_engine_review"

# The default options' decisions, as the console sends them, and the ports they choose.
DEFAULT_DECISIONS = {"approved": "approve", "rejected": "reject", "approve": "approve", "reject": "reject"}


def is_engine_id(review_id: str) -> bool:
    return review_id.startswith(RUN_PREFIX)


def _runs(rt: Runtime) -> RunStore:
    return RunStore(EngineTransactions(rt.db))


async def _visible(rt: Runtime, run_id: str) -> dict[str, Any]:
    """The run behind a review, if the selected team may see it (routers/engine.visible_run); else not found."""
    from .routers.engine import visible_run  # noqa: PLC0415 - the router imports the Reviews facade's neighbours

    try:
        return await visible_run(rt, run_id)
    except NotFound as e:
        raise NotFound("Review") from e


def _options(payload: dict[str, Any]) -> list[str]:
    raw = cast(list[Any], payload.get("options") or [])
    return [str(cast(dict[str, Any], o).get("name") if isinstance(o, dict) else o) for o in raw]


def step_id(run: dict[str, Any], payload: dict[str, Any]) -> str:
    """A v2 review's id: its step (run:node:iteration), so two review steps of one run are two reviews."""
    return str(payload.get("step_id") or run["id"])


def run_of(review_id: str) -> str:
    return review_id.split(":", 1)[0]


def _calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    listed = [cast(dict[str, Any], o) for o in cast(list[Any], payload.get("options") or []) if isinstance(o, dict)]
    found = [payload.get("call"), *(o.get("call") for o in listed)]
    return [cast(dict[str, Any], c) for c in found if isinstance(c, dict)]


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def typed_fields(draft: Any, calls: list[dict[str, Any]]) -> dict[str, Any]:
    """What a review row shows from its step's summary and proposed calls, for any workflow: the customer (the summary's
    matched customer, else its record's name), the amount the first call would act on, that call's account currency
    (none when no account was read), and the proposal as one readable line instead of the summary's raw dict."""
    d = cast(dict[str, Any], draft) if isinstance(draft, dict) else {}
    customer, record = d.get("customer"), d.get("record")
    found: dict[str, Any] = cast(dict[str, Any], customer) if isinstance(customer, dict) else {}
    read: dict[str, Any] = cast(dict[str, Any], record) if isinstance(record, dict) else {}
    name = found.get("name") or (customer if isinstance(customer, str) else None) or read.get("name")
    first = calls[0] if calls else {}
    args = cast(dict[str, Any], first.get("input") or {})
    amount = _number(args.get("amount"))
    if amount is None:
        amount = _number(read.get("amount"))
    accounts = [cast(dict[str, Any], a) for a in cast(list[Any], d.get("accounts") or []) if isinstance(a, dict)]
    account = next((a for a in accounts if a.get("id") == args.get("account_id")), accounts[0] if accounts else {})
    if first.get("tool"):
        proposal = f"{first['tool']}: " + ", ".join(f"{k} {v}" for k, v in args.items())
    else:
        proposal = draft if isinstance(draft, str) else "" if draft is None else json.dumps(draft, default=str)
    return {
        "customer": str(name or ""),
        "amount": amount,
        "currency": str(account["currency"]) if account.get("currency") else None,
        "proposal": proposal,
    }


def _read_in(draft: Any) -> dict[str, Any] | None:
    """The Extract from file result a review's summary holds (a value with its file, field schema and records or
    fields), whatever key the workflow gave it."""
    if not isinstance(draft, dict):
        return None
    for value in cast(dict[str, Any], draft).values():
        if is_read(value):
            return cast(dict[str, Any], value)
    return None


def _combined_in(draft: Any) -> dict[str, Any] | None:
    """A Combine facts result the summary holds (its values, the source each came from, and the fields the sources
    disagree on), whatever key the workflow gave it."""
    if not isinstance(draft, dict):
        return None
    for value in cast(dict[str, Any], draft).values():
        if isinstance(value, dict):
            v = cast(dict[str, Any], value)
            if isinstance(v.get("sources"), dict) and isinstance(v.get("conflicts"), list) and "values" in v:
                return v
    return None


def _plain(value: Any) -> Any:
    """A source's value as a person reads it: an extracted field's `value`, anything else as it is."""
    if isinstance(value, dict):
        found = cast(dict[str, Any], value)
        if "value" in found:
            return found["value"]
    return cast(Any, value)


def _by_source(record: dict[str, Any], combined: dict[str, Any]) -> list[str]:
    """Marks each field of a one-record read with every source's value and whether they disagree; returns the sources
    in the order they first appear. A field the sources agree on shows the value of the source it was taken from."""
    picked = cast(dict[str, Any], combined.get("sources") or {})
    values = cast(dict[str, Any], combined.get("values") or {})
    disputed: dict[str, list[dict[str, Any]]] = {}
    for c in cast(list[Any], combined.get("conflicts") or []):
        if isinstance(c, dict):
            row = cast(dict[str, Any], c)
            disputed[str(row.get("field"))] = [
                cast(dict[str, Any], x) for x in cast(list[Any], row.get("values") or []) if isinstance(x, dict)
            ]
    names: list[str] = []
    for key, field in cast(dict[str, dict[str, Any]], record["fields"]).items():
        seen = {str(x.get("source")): _plain(x.get("value")) for x in disputed.get(key, [])}
        if not seen and key in picked:
            seen = {str(picked[key]): _plain(values.get(key))}
        if seen:
            field["bySource"] = seen
            field["conflict"] = key in disputed
            names.extend(n for n in seen if n not in names)
    return names


def _field(scored: Any) -> dict[str, Any]:
    s = cast(dict[str, Any], scored) if isinstance(scored, dict) else {}
    cited = cast(dict[str, Any], s.get("citation") or {})
    return {
        "value": s.get("value"),
        "extractedValue": s.get("extractedValue"),
        "confidence": _number(s.get("confidence")),
        "needsReview": bool(s.get("needsReview")),
        "citation": {"page": cited.get("page"), "quote": cited.get("quote")} if cited else None,
        "boxes": [
            b for b in cast(list[Any], s.get("boxes") or []) if isinstance(b, dict) and _is_box(cast(dict[str, Any], b))
        ],
    }


def _task_words(task: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """A typed review's row words from its task: the header's title and the message as the reason, and whoever the step
    names as having asked, so a list row reads as the task screen does whatever the workflow."""
    data = {str(r["region"]): cast(dict[str, Any], r.get("data") or {}) for r in task["regions"]}
    words: dict[str, Any] = {}
    if title := data.get("header", {}).get("title"):
        words["title"] = str(title)
    if text := data.get("message", {}).get("text"):
        words["reasoning"] = [str(text)]
    if asked := [str(x) for x in cast(list[Any], payload.get("requestedBy") or []) if x]:
        words["customer"] = f"Requested by {', '.join(asked)}"
    return words


def _is_box(b: dict[str, Any]) -> bool:
    """A box the console can place: a page and four fractions. Anything else from the read is left out."""
    return isinstance(b.get("page"), int) and all(isinstance(b.get(k), (int, float)) for k in ("x", "y", "w", "h"))


def read_view(read: dict[str, Any], file_name: str | None, edited: Any) -> dict[str, Any]:
    """An Extract from file result as people read it, wherever it is shown (Human Tasks, a run's page): the file, the
    floor, each field's label, and per record each field's value, confidence and page quote, with the corrected values a
    person approved it with (`edited`, the whole records list) or None. Nothing takes a correction here; the caller says
    whether its step does (`editable`)."""
    rows: list[Any] = []
    if "records" in read:
        rows = cast(list[Any], read.get("records") or [])
    elif isinstance(read.get("fields"), dict):
        # A one-record read: its fields as one record, with the values the next step reads.
        fields = cast(dict[str, Any], read["fields"])
        rows = [{"values": {k: cast(dict[str, Any], f).get("value") for k, f in fields.items()}, "fields": fields}]
    records: list[dict[str, Any]] = []
    for row in rows:
        r = cast(dict[str, Any], row) if isinstance(row, dict) else {}
        scored = cast(dict[str, Any], r.get("fields") or {})
        records.append(
            {
                "values": dict(cast(dict[str, Any], r.get("values") or {})),
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
            for f in (cast(dict[str, Any], x) for x in cast(list[Any], read.get("schema") or []) if isinstance(x, dict))
        ],
        "records": records,
        "sources": [],
        "editable": False,
        "corrected": [dict(cast(dict[str, Any], r).get("values") or {}) for r in cast(list[Any], edited)]
        if isinstance(edited, list)
        else None,
    }


def is_read(value: Any) -> bool:
    """Whether a value is an Extract from file result: its file, the type's field schema, and records or fields."""
    if not isinstance(value, dict):
        return False
    v = cast(dict[str, Any], value)
    return "fileId" in v and isinstance(v.get("schema"), list) and ("records" in v or "fields" in v)


def document_read(draft: Any, payload: dict[str, Any], resume: dict[str, Any] | None) -> dict[str, Any] | None:
    """A document read as Human Tasks shows it (read_view), with whether the step takes a correction and, for a
    one-record read a Combine facts step weighed, each source's value."""
    read = _read_in(draft)
    if read is None:
        return None
    # Workflows name the file under `document` (the levy flows) or `file` (system extract); either is the file name.
    name = cast(dict[str, Any], draft).get("document") or cast(dict[str, Any], draft).get("file")
    view = read_view(read, str(name) if isinstance(name, str) and name else None, (resume or {}).get("edited"))
    combined = _combined_in(draft)
    # Several sources side by side only for a one-record read: Combine facts merges one set of fields.
    if combined is not None and len(view["records"]) == 1:
        view["sources"] = _by_source(view["records"][0], combined)
    view["editable"] = isinstance(payload.get("editable"), dict)
    return view


async def reply_preview(rt: Runtime, team: str, draft: Any, call: dict[str, Any]) -> dict[str, Any] | None:
    """The reply a review approves (its send_reply call) as it will leave, with the cases the summary's started runs
    are on; a run that has not opened its case yet has none."""
    if call.get("tool") != "send_reply":
        return None
    args = cast(dict[str, Any], call.get("input") or {})
    summary = cast(dict[str, Any], draft) if isinstance(draft, dict) else {}
    started = summary.get("cases")
    listed = cast(list[Any], cast(dict[str, Any], started).get("runs") or []) if isinstance(started, dict) else []
    rows = [cast(dict[str, Any], r) for r in listed if isinstance(r, dict)]
    runs = [r for r in rows if r.get("runId")]
    store = CaseStore(rt.db)
    on_case = await store.cases_of_runs([str(r["runId"]) for r in runs])
    # Each case by its subject, so the reviewer reads who it is about rather than an id; the run's child runs and the
    # cases they opened are in the run's team.
    subjects: dict[str, str] = {}
    for case_id in {c for c in on_case.values() if c}:
        with contextlib.suppress(CaseNotFound):
            subjects[case_id] = str((await store.get(case_id, [team])).get("subject") or "")
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


def _read_line(read: dict[str, Any]) -> tuple[str, str]:
    """The row's customer and proposal for a document read: who it names and what a person is asked to check."""
    names = [str(r["values"].get("name")) for r in read["records"] if r["values"].get("name")]
    doubtful = sum(1 for r in read["records"] for f in r["fields"].values() if f["needsReview"])
    count = len(read["records"])
    of = f" from {read['fileName']}" if read["fileName"] else ""
    check = f"; {doubtful} field{'s' if doubtful != 1 else ''} to check" if doubtful else ""
    return ", ".join(names), f"Read {count} record{'s' if count != 1 else ''}{of}{check}"


async def titles_of(rt: Runtime, run: dict[str, Any]) -> dict[str, Any]:
    """The run's workflow by its display name and each step by its own, from the version the run pinned."""
    stored = await DefinitionStore(EngineTransactions(rt.db)).get(str(run["workflow_id"]), run.get("version"))
    return _titles(run, stored)


async def titles_by_run(rt: Runtime, runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """titles_of for each run, the versions they pinned read in one query, with the version that now serves each run's
    workflow (`live`, read in one more) for a review older than typed steps (legacy_tasks)."""
    keys = {(str(r["workflow_id"]), int(r["version"])) for r in runs if r.get("version") is not None}
    store = DefinitionStore(EngineTransactions(rt.db))
    stored = await store.pinned(keys)
    serving = await store.currents({str(r["workflow_id"]) for r in runs})
    return {
        str(r["id"]): _titles(r, stored.get((str(r["workflow_id"]), int(r.get("version") or 0))))
        | {"live": serving.get(str(r["workflow_id"]))}
        for r in runs
    }


def _titles(run: dict[str, Any], stored: dict[str, Any] | None) -> dict[str, Any]:
    definition = cast(dict[str, Any], (stored or {}).get("definition") or {})
    nodes = [cast(dict[str, Any], n) for n in cast(list[Any], definition.get("nodes") or []) if isinstance(n, dict)]
    return {
        "workflow": str((stored or {}).get("name") or run["workflow_id"]),
        "steps": {str(n.get("id")): str(n.get("name") or n.get("id")) for n in nodes},
    }


ON_TIMEOUT = {"expire": "Expires: takes the timeout path", "wait": "Stays open, shows overdue"}


def review_deadline(payload: dict[str, Any], workspace_hours: float, now: datetime) -> dict[str, Any]:
    """The step's deadline as the row and sheet show it: its own slaHours, else the workspace's review deadline,
    counted from when it opened. A step paused before deadlines were recorded has no openedAt and no countdown."""
    own = payload.get("slaHours")
    hours = float(own) if own is not None else workspace_hours
    sla = f"{hours:g}h" + ("" if own is not None else " (workspace)")
    opened = payload.get("openedAt")
    out: dict[str, Any] = {
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


def as_decided(payload: dict[str, Any], resume: dict[str, Any]) -> dict[str, Any]:
    """The paused step's payload with the call its decision sent in place of the one proposed, so a decided review reads
    what was done: an approver who changed an input (a hold's amount) sees that value, as the bank was told (c-420).
    A new payload; the stored one is left as it is."""
    sent = resume.get("call")
    if not isinstance(sent, dict):
        return payload
    if isinstance(payload.get("call"), dict):
        return payload | {"call": sent}
    listed = cast(list[Any], payload.get("options") or [])
    chosen = resume.get("option")
    return payload | {
        "options": [
            cast(dict[str, Any], o) | {"call": sent}
            if isinstance(o, dict) and cast(dict[str, Any], o).get("name") == chosen
            else o
            for o in listed
        ]
    }


async def view(
    rt: Runtime,
    run: dict[str, Any],
    decided: dict[str, Any] | None = None,
    *,
    case_id: str | None = None,
    titles: dict[str, Any] | None = None,
    reads: TaskReads | None = None,
) -> dict[str, Any]:
    """A review step of a run as a console `Review`: risk and step-up from the operations its options would call,
    as v1's review_view reads them. `case_id` is the case the run is on (c-128) and `titles` the workflow's and its
    steps' names (titles_of), each looked up when not given; `reads` what a list of typed tasks reads once
    (TaskReads)."""
    if case_id is None:
        case_id = (await CaseStore(rt.db).cases_of_runs([str(run["id"])])).get(str(run["id"]))
    if titles is None:
        titles = await titles_of(rt, run)
    payload = _payload(run, decided)
    options = _options(payload)
    calls = _calls(payload)
    policies = [await policy_of(rt, str(c["tool"])) for c in calls if c.get("tool")]
    two = any(p.approvers > 1 for p in policies)
    # Who decides it, as _check_decider checks: a write's approving team, else the run's team.
    approving = next((p.approver_team for p in policies if p.approver_team), None)
    step_up = any(p.step_up for p in policies)
    draft = payload.get("draft")
    call = calls[0] if calls else {}
    deadline = review_deadline(payload, await sla_hours(rt), datetime.now(UTC))
    typed = typed_fields(draft, calls)
    # Each call in words (c-289); typed_fields reads the input named amount as the review's amount, so that input is
    # shown as money in the account's currency.
    money_key = "amount" if typed["amount"] is not None else None
    described = [await describe_call(rt, c, currency=typed["currency"], money_key=money_key) for c in calls]
    declared = [cast(dict[str, Any], o) for o in cast(list[Any], payload.get("options") or []) if isinstance(o, dict)]
    labels = {str(o.get("name")): str(o.get("label") or str(o.get("name")).capitalize()) for o in declared}
    said = {id(c): d for c, d in zip(calls, described, strict=True)}

    def option_view(name: str) -> dict[str, Any]:
        opt_call = next((o.get("call") for o in declared if str(o.get("name")) == name), None)
        d = said.get(id(cast(dict[str, Any], opt_call))) if isinstance(opt_call, dict) else None
        return {
            "name": name,
            "label": labels.get(name, name.capitalize()),
            "consequence": (d["consequence"] or d["sentence"]) if d else None,
            "fields": d["fields"] if d else [],
        }

    out: dict[str, Any] = {
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
        "kind": "approval",
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
        "decidingTeam": await deciding_team(rt, approving or run.get("team_id")),
        **typed,
    }
    if task := await typed_task(rt, payload, run, reads):
        out["task"] = task
        out |= _task_words(task, payload)
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
    read = document_read(draft, payload, cast(dict[str, Any], (decided or {}).get("resume") or {}))
    if read is not None:
        out["customer"], out["proposal"] = _read_line(read)
        out["read"] = read
    if calls and (reply := await reply_preview(rt, str(run["team_id"]), draft, calls[0])) is not None:
        out["reply"] = reply
    if decided is not None:
        resume = cast(dict[str, Any], decided.get("resume") or {})
        out |= {
            "status": _decided_status(decided),
            "decidedAt": decided.get("at"),
            "decisionReason": resume.get("reason"),
            "option": resume.get("option"),
            "decidedBy": resume.get("by"),
            "resume": resume,
            "stepUpRef": None,
        }
    # A review older than typed steps draws through a task type too (tick 31), from the words built above.
    if "task" not in out and (
        legacy := await legacy_task(rt, run, payload, out, live=titles.get("live", NOT_READ), reads=reads)
    ):
        out["task"] = legacy
    return out


async def _decisions(rt: Runtime, run_id: str) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], w["payload"]) for w in await _runs(rt).work(run_id) if w["kind"] == "resume"]


def _payload(run: dict[str, Any], decided: dict[str, Any] | None) -> dict[str, Any]:
    """The step's payload as its review reads it: the decided call in place of the proposed one once decided."""
    waiting: dict[str, Any] = dict(run.get("waiting") or {})
    payload: dict[str, Any] = dict((decided or {}).get("payload") or waiting.get("payload") or {})
    if decided is not None:
        payload = as_decided(payload, cast(dict[str, Any], decided.get("resume") or {}))
    return payload


def _risk(policies: list[WritePolicy]) -> str:
    """A step whose call needs two approvers is high risk, any other write medium, a read low."""
    if any(p.approvers > 1 for p in policies):
        return "high"
    return "medium" if any(p.access == "write" for p in policies) else "low"


async def all_rows(rt: Runtime) -> list[dict[str, Any]]:
    """Each review step of the selected team's runs (the one a run waits on as pending, and every decided one) as a
    row holding what the list counts, filters, facets and pages on: id, status, title, risk, workflow, deadline, case
    and when it opened and was decided. No typed task, wording or reply preview is read; `expand` builds the full
    review for the rows a page shows, so a count reads no more than its rows (c-451)."""
    try:
        runs = await _runs(rt).list(team_id=current_team())
    except DatabaseError as e:  # A database not yet migrated to the runner's tables lists v1 reviews alone.
        log.warning("engine_reviews_unavailable", error=type(e).__name__)
        return []
    on_case = await CaseStore(rt.db).cases_of_runs([str(r["id"]) for r in runs])
    decisions = await _runs(rt).resumes([str(r["id"]) for r in runs])
    steps: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for run in runs:
        steps += [(run, d) for d in decisions.get(str(run["id"]), [])]
        if run["status"] == "waiting" and run.get("waiting"):
            steps.append((run, None))
    payloads = [_payload(run, d) for run, d in steps]
    # Every tool the steps call, asked at once; within one_read_per_tool each is then asked once for the request.
    tools = sorted({str(c["tool"]) for p in payloads for c in _calls(p) if c.get("tool")})
    await asyncio.gather(*(policy_of(rt, t) for t in tools))
    hours = await sla_hours(rt)
    now = datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for (run, decided), payload in zip(steps, payloads, strict=True):
        policies = [await policy_of(rt, str(c["tool"])) for c in _calls(payload) if c.get("tool")]
        row: dict[str, Any] = {
            "id": step_id(run, payload),
            "title": str(payload.get("title") or f"Review {run['workflow_id']}"),
            "workflowId": run["workflow_id"],
            "agentSlug": run["workflow_id"],
            "kind": "approval",
            "risk": _risk(policies),
            "status": "pending" if decided is None else _decided_status(decided),
            "slaMinutes": review_deadline(payload, hours, now)["minutes"] if decided is None else None,
            "createdAt": run["updated_at"],
            # "" says "looked up, on no case", so expand does not ask again per row.
            "caseId": on_case.get(str(run["id"])) or None,
            BUILD: (run, decided, on_case.get(str(run["id"]), "")),
        }
        if decided is not None:
            row["decidedAt"] = decided.get("at")
        out.append(row)
    return out


async def expand(rt: Runtime, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each row all_rows made, as its full review (who it is assigned to kept); every other row as it is. What the
    rows' typed tasks and titles read is read once for all of them."""
    light = [r for r in rows if BUILD in r]
    if not light:
        return rows
    runs = list({str(r[BUILD][0]["id"]): r[BUILD][0] for r in light}.values())
    named = await titles_by_run(rt, runs)
    payloads = [_payload(r[BUILD][0], r[BUILD][1]) for r in light]
    reads = TaskReads(rt, runs, [str(p["step_id"]) for p in payloads if p.get("step_id")])
    built: dict[int, dict[str, Any]] = {}
    for r in light:
        run, decided, case_id = r[BUILD]
        full = await view(rt, run, decided, case_id=case_id, titles=named[str(run["id"])], reads=reads)
        built[id(r)] = full | ({"assignee": r["assignee"]} if "assignee" in r else {})
    return [built.get(id(r), r) for r in rows]


async def all_places(rt: Runtime) -> list[dict[str, Any]]:
    """all_views' reviews by id and status alone, in its order: a task's place in its queue (hitl_facade.queue_place)
    reads no task type, policy or wording."""
    try:
        runs = await _runs(rt).list(team_id=current_team())
    except DatabaseError as e:
        log.warning("engine_reviews_unavailable", error=type(e).__name__)
        return []
    decisions = await _runs(rt).resumes([str(r["id"]) for r in runs])
    out: list[dict[str, Any]] = []
    for run in runs:
        for d in decisions.get(str(run["id"]), []):
            out.append({"id": step_id(run, cast(dict[str, Any], d.get("payload") or {})), "status": _decided_status(d)})
        if run["status"] == "waiting" and run.get("waiting"):
            waiting = cast(dict[str, Any], dict(run["waiting"]).get("payload") or {})
            out.append({"id": step_id(run, waiting), "status": "pending"})
    return out


def _decided_status(decided: dict[str, Any]) -> str:
    resume = cast(dict[str, Any], decided.get("resume") or {})
    approved = resume.get("decision") in ("approved", "approve") and resume.get("option") != "reject"
    return "approved" if approved else "rejected"


async def get(rt: Runtime, review_id: str) -> dict[str, Any]:
    """A review by its step id; a run id names the step the run waits on, else its latest decision."""
    run = await _visible(rt, run_of(review_id))
    waiting = dict(run.get("waiting") or {})
    if run["status"] == "waiting" and waiting and review_id in (run["id"], step_id(run, waiting.get("payload") or {})):
        return await view(rt, run)
    decided = [
        d for d in await _decisions(rt, run["id"]) if review_id in (run["id"], step_id(run, d.get("payload") or {}))
    ]
    if decided:
        return await view(rt, run, decided[-1])
    raise NotFound("Review")


async def _check_decider(rt: Runtime, approver: Principal, run: dict[str, Any], calls: list[dict[str, Any]]) -> None:
    """Who may decide a run's review: a reviewer or admin of the run's team unless a policy of the writes it decides
    (`calls`) names an approving team, which is required instead, and not who started the run or whom the step names in
    requestedBy while requesterMayDecide is off. Anyone the step names in notDecidedBy is refused whatever the policy,
    such as whoever saved the version it approves."""
    from .hitl_facade import require_approver_team  # noqa: PLC0415 - hitl_facade imports this module

    paused = cast(dict[str, Any], dict(run.get("waiting") or {}).get("payload") or {})
    barred = {str(x).lower() for x in cast(list[Any], paused.get("notDecidedBy") or [])}
    if approver.email.lower() in barred:
        raise Forbidden("You are named as not deciding this review; another reviewer must.", code="not_decided_by")
    teams, approving = review_teams(approver), None
    for call in calls:
        policy = await policy_of(rt, str(call["tool"]))
        require_approver_team(policy, teams, str(call["tool"]))
        approving = approving or policy.approver_team
    if not approving:
        require_reviews_decide(teams, str(run["team_id"]), "this review")
    # Who started the run, and whoever the step names as having asked (an event's requester), under the same policy.
    asked = [run["created_by"], *(str(x) for x in cast(list[Any], paused.get("requestedBy") or []))]
    require_not_own(approver, asked, team=approving or str(run["team_id"]), what="this run's review")


async def check_decider(rt: Runtime, approver: Principal, review_id: str) -> None:
    """The decision route's checks on a waiting run's review, without deciding it (c-123's canDecide)."""
    run = await _visible(rt, run_of(review_id))
    waiting: dict[str, Any] = dict(run.get("waiting") or {})
    if not waiting:
        raise Conflict("This run is not waiting for a decision.", code="run_not_waiting")
    await _check_decider(rt, approver, run, held_calls(cast(dict[str, Any], waiting.get("payload") or {})))


NOTHING = object()


def _record_keys(row: Any) -> set[str] | None:
    """The field names of one record (`{"values": {...}}`), or None when it is not one."""
    if not isinstance(row, dict):
        return None
    values = cast(dict[str, Any], row).get("values")
    return {str(k) for k in cast(dict[str, Any], values)} if isinstance(values, dict) else None


def correction(paused: dict[str, Any], inputs: dict[str, Any] | None) -> tuple[Any, dict[str, Any] | None]:
    """A reviewer's correction (`inputs.edited`) of the step's editable value, checked against it, and the inputs left
    for the option's call. A list of records keeps each record's `values` to the keys the read has; a dict keeps its own
    keys. NOTHING when no correction was sent."""
    rest = dict(inputs or {})
    if "edited" not in rest:
        return NOTHING, inputs
    edited: Any = rest.pop("edited")
    editable = paused.get("editable")
    if not isinstance(editable, dict):
        raise ValidationFailed("This review has nothing to correct.")
    was: Any = cast(dict[str, Any], editable).get("value")
    if isinstance(was, list):
        allowed: set[str] = set()
        for row in cast(list[Any], was):
            allowed |= _record_keys(row) or set()
        if not isinstance(edited, list):
            raise ValidationFailed("A correction lists the records, each with its values.")
        found: set[str] = set()
        for row in cast(list[Any], edited):
            keys = _record_keys(row)
            if keys is None:
                raise ValidationFailed("A correction lists the records, each with its values.")
            found |= keys
        unknown = sorted(found - allowed)
    elif isinstance(was, dict):
        if not isinstance(edited, dict):
            raise ValidationFailed("A correction has the same fields as what was read.")
        unknown = sorted({str(k) for k in cast(dict[str, Any], edited)} - {str(k) for k in cast(dict[str, Any], was)})
    else:
        raise ValidationFailed("This review's value cannot be corrected.")
    if unknown:
        raise ValidationFailed(f"A correction names fields the read does not have: {', '.join(unknown)}.")
    return cast(Any, edited), rest or None


async def decide(
    rt: Runtime,
    approver: Principal,
    run_id: str,
    *,
    decision: str,
    reason: str | None,
    step_up_token: str | None = None,
    inputs: dict[str, Any] | None = None,
    amount: float | None = None,
) -> dict[str, Any]:
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
    waiting: dict[str, Any] = dict(run.get("waiting") or {})
    if waiting and review_id not in (run_id, step_id(run, waiting.get("payload") or {})):
        waiting = {}  # an earlier review step of this run: answered from its decision below
    if not waiting:
        earlier = await _decisions(rt, run_id)
        if earlier:
            was = cast(dict[str, Any], earlier[-1].get("resume") or {})
            if decision in (was.get("decision"), was.get("option")):
                return await view(rt, run, earlier[-1])
            raise Conflict(
                f"This review was already decided: {was.get('option') or was.get('decision')}.", code="already_decided"
            )
        raise Conflict("This run is not waiting for a decision.", code="run_not_waiting")
    paused = cast(dict[str, Any], waiting.get("payload") or {})
    edited, inputs = correction(paused, inputs)
    options = _options(paused)
    call: dict[str, Any] | None = None
    if options:
        if decision not in options:
            raise ValidationFailed(f"This review is decided with one of: {', '.join(options)}.")
        # The reject option rejects, as Reject does on a step without options; every other option approves its call.
        resume: dict[str, Any] = {"decision": "rejected" if decision == "reject" else "approved", "option": decision}
        declared = [cast(dict[str, Any], o) for o in cast(list[Any], paused["options"]) if isinstance(o, dict)]
        chosen = next((o for o in declared if o.get("name") == decision), None)
        if chosen is not None and chosen.get("call"):
            from .hitl_facade import option_call  # noqa: PLC0415 - hitl_facade imports this module

            call = option_call(chosen, inputs, amount)
    else:
        if decision not in DEFAULT_DECISIONS:
            raise ValidationFailed("This review is approved or rejected.")
        resume = {"decision": "approved" if DEFAULT_DECISIONS[decision] == "approve" else "rejected"}
        if resume["decision"] == "approved" and paused.get("call"):
            call = dict(cast(dict[str, Any], paused["call"]))
    if paused.get("taskType"):
        rest = dict(inputs or {})
        confirmed = rest.pop("confirmed", None)
        action = await _typed_action(rt, run, paused, str(resume.get("option") or DEFAULT_DECISIONS[decision]))
        if action.get("requires"):
            _check_requirement(str(action["requires"]), paused, confirmed)
            resume["confirmed"] = confirmed
        if call is None and rest:
            # A typed action's own inputs (a Reject's assignee) travel to the workflow with the decision (c-329).
            resume["inputs"] = _action_inputs(action, rest)
    # An approval is checked against the call it sends; a rejection against every write the step holds.
    await _check_decider(rt, approver, run, [call] if call is not None else held_calls(paused))
    resume |= {"reason": reason, "by": approver.email}
    if edited is not NOTHING and resume["decision"] == "approved":
        resume["edited"] = edited
    if call is not None:
        approval = await _approve_call(
            rt, approver, run_id, call, step_up_token=step_up_token, team_id=str(run["team_id"])
        )
        if approval is None:
            return await view(rt, run) | {"status": "in_review"}
        # A reference to the recorded approvals, never the token: the worker mints the token from them when it calls
        # the gateway, so no token is stored in the queue, the journal or a run's detail.
        resume |= {"call": call, "approval": approval}
    key = f"resume:{run_id}:{waiting['node']}:{waiting['iteration']}"
    payload = {
        "resume": resume,
        "payload": waiting.get("payload"),
        "at": now_iso(),
        "interruptId": waiting.get("interruptId"),
    }
    queue = WorkQueue(EngineTransactions(rt.db), owner="api", ttl=rt.settings.lease_ttl_seconds)
    row, created = await queue.enqueue(run_id, "resume", key, payload)
    stored = cast(dict[str, Any], row["payload"])
    if not created:
        was = cast(dict[str, Any], stored.get("resume") or {})
        if was.get("decision") != resume["decision"] or was.get("option") != resume.get("option"):
            raise Conflict("This review was already decided.", code="already_decided")
        return await view(rt, run, stored)
    await runs.update(run_id, status="queued", waiting=None)
    await EventLog(rt.db).append(
        thread_id=run_id,
        team_id=run["team_id"],
        run_id=run_id,
        type_="decided",
        node=str(waiting["node"]),
        data={"decision": resume["decision"], "option": resume.get("option"), "decidedBy": approver.email},
    )
    cases = CaseStore(rt.db)
    case_id = (await cases.cases_of_runs([run_id])).get(run_id)
    if case_id is not None:
        # The decision is on the case's timeline too (c-128): the case reads as the issue's whole history.
        detail = {"decision": resume["decision"], "option": resume.get("option"), "reason": reason}
        await cases.add_event(case_id, "decision", ref=step_id(run, paused), detail=detail, by=approver.email)
    return await view(rt, run, stored, case_id=case_id or "")


async def _approve_call(
    rt: Runtime,
    approver: Principal,
    run_id: str,
    call: dict[str, Any],
    *,
    step_up_token: str | None,
    team_id: str,
) -> dict[str, Any] | None:
    """Records `approver`'s approval of `call` in the run's team (`team_id`) and returns the approval reference
    ({step, inputHash, approvers}) once as many distinct people as its policy names have approved this exact input;
    None while more are needed."""
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


async def _typed_action(rt: Runtime, run: dict[str, Any], paused: dict[str, Any], port: str) -> dict[str, Any]:
    """The task type's action that leads to `port`, from the type version the step names in the run's team; empty when
    it has none."""
    ref = cast(dict[str, Any], paused["taskType"])
    types = await task_type_store(rt, str(run["team_id"]))
    _, record = await types.published(str(ref["id"]), cast(int | None, ref.get("version")))
    actions = cast(list[dict[str, Any]], record.get("actions") or [])
    none: dict[str, Any] = {}
    return next((a for a in actions if a.get("port") == port), none)


# An action input naming a person (a task type's `format: person`), and the shape that names one.
PERSON = "person"
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _action_inputs(action: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """The inputs `action` declares, checked: one it does not declare, or a required one left out, is refused naming
    it, so a misspelt assignee never silently leaves the task with the team."""
    declared = {str(i["name"]): i for i in cast(list[dict[str, Any]], action.get("inputs") or [])}
    if unknown := sorted(set(inputs) - set(declared)):
        raise ValidationFailed(f"This action takes no {', '.join(unknown)}.")
    if missing := sorted(n for n, i in declared.items() if i.get("required") and inputs.get(n) in (None, "")):
        raise ValidationFailed(f"This action needs {', '.join(missing)}.")
    # A person is named by email, as assignments are; empty leaves the task with the team's queue.
    if named := sorted(
        n
        for n, i in declared.items()
        if i.get("format") == PERSON and inputs.get(n) not in (None, "") and not _EMAIL.fullmatch(str(inputs[n]))
    ):
        raise ValidationFailed(f"{', '.join(named)} names a person by email.")
    return dict(inputs)


def _key_fields_left(paused: dict[str, Any], confirmed: Any) -> int:
    """How many key fields of the step's read are not in `confirmed` (record index to field keys), counted as the
    console's keyFieldsLeft counts them; 0 when the read marks none or there is no read."""
    read = document_read(paused.get("draft"), paused, None)
    if read is None:
        return 0
    given = cast(dict[Any, Any], confirmed) if isinstance(confirmed, dict) else {}
    keys = [str(f["key"]) for f in cast(list[dict[str, Any]], read["schema"]) if f["keyField"]]
    left = 0
    for i in range(len(cast(list[Any], read["records"]))):
        seen = given.get(str(i), given.get(i))
        done = {str(k) for k in cast(list[Any], seen)} if isinstance(seen, list) else set[str]()
        left += sum(k not in done for k in keys)
    return left


def _key_fields_confirmed(paused: dict[str, Any], confirmed: Any) -> None:
    if left := _key_fields_left(paused, confirmed):
        what = "1 key field" if left == 1 else f"{left} key fields"
        raise ValidationFailed(f"Confirm {what} before approving.", code="key_fields_unconfirmed")


# What a task type's action can wait for (its `requires`), checked on the decision as the console blocks the button,
# so a call that skips the console cannot approve values nobody checked.
REQUIREMENTS: dict[str, Callable[[dict[str, Any], Any], None]] = {"key_fields_confirmed": _key_fields_confirmed}


def _check_requirement(name: str, paused: dict[str, Any], confirmed: Any) -> None:
    check = REQUIREMENTS.get(name)
    if check is None:
        # A type naming a rule this service cannot check is refused rather than approved unchecked.
        raise ValidationFailed(
            f"This action waits for {name}, which cannot be checked here.", code="unknown_requirement"
        )
    check(paused, confirmed)
