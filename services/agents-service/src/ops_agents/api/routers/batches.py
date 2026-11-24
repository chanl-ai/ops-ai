"""Batches: start a workflow once per row of a CSV or Excel file, then follow it on its own page.

The file is read from Files as the caller's team; its header row names the workflow's inputs, by key or by the title
the start form shows. A dry run answers the row count, how the columns map and the first five rows, and starts
nothing. A file over 500 rows, or one whose header names none of the inputs, is refused before anything starts. The
workflow worker starts the rows (`api/batches.py`); this page reads their runs back."""

from __future__ import annotations

import csv
import io
import json
from typing import Annotated, Any, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from ops_access import can
from ops_agent_kernel.pii import masked
from ops_engine import default_registry
from ops_engine.node_types import start_form
from ops_engine.store import DefinitionRow
from ops_files_client import FileNotFound, FilesClient
from ops_identity.fastapi import Tx
from ops_ingest.parsers.spreadsheet import spreadsheet_rows
from ops_service_kit.errors import NotFound, ServiceUnavailable, Unprocessable
from ops_service_kit.http import Envelope, In, Json, JsonValue, ListResult, Out
from ops_service_kit.listing import ListQuery
from ops_store import isolation

from ...store.batches import MAX_ROWS, Batches, BatchOut, BatchRowOut
from ...store.tenancy import current_team, current_tenant
from ...store.waiting_files import WaitingFiles
from .. import ai_steps_gate
from ..auth import ACCESS, Principal, caller_of, principal, reader_of, started_by
from ..deps import Runtime, runtime
from ..engine_runs import checked_input
from ..envelope import ok
from .engine import definitions, startable

router = APIRouter(tags=["batches"])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040
# A batch's page and results show every row's input and output, so they are read with workflows.view.
Reader: TypeAlias = Annotated[Principal, Depends(reader_of("workflows"))]  # noqa: UP040
SAMPLE = 5
# Every status a row can hold that is not a run under way.
NOT_RUNNING = ("succeeded", "failed", "cancelled", "pending", "waiting", "removed")


class BatchIn(In):
    file_id: str = Field(min_length=1, max_length=64)
    mode: Literal["live", "test"] = "live"
    dry_run: bool = False


class DryRun(Out):
    rows: int
    # Each column of the header that names an input, and the input's key.
    mapping: dict[str, str]
    # Columns that name no input, left out of every run.
    ignored: list[str]
    sample: list[dict[str, JsonValue]]


class BatchStarted(Out):
    id: str
    total: int


class BatchRow(Out):
    row: int
    attempt: int
    # pending until its run starts, then the run's own status; removed or failed for a check's file that never ran.
    status: str
    failure_code: str | None = None
    reason: str | None = None
    outcome: str | None = None
    output: JsonValue = None
    error: str | None = None
    run_id: str | None = None
    input: dict[str, JsonValue]


class Stopped(Out):
    reason: str
    at: str


class BatchView(Out):
    id: str
    workflow_id: str
    # upload: a spreadsheet's rows; check: one check of a watched folder, whose label is the file name.
    origin: str
    file_name: str
    watch_id: str | None = None
    checked_at: str | None = None
    mode: str
    total: int
    finished: int
    failed: int
    running: int
    # Runs paused on a person or a timer, counted apart from running.
    waiting: int
    pending: int
    removed: int
    # Failed rows whose run failed, which retry starts again; a file that never ran is not retried.
    retryable: int
    not_retryable: int
    may_retry: bool
    stopped: Stopped | None = None
    # The group the check's files were split into (Group by), its named parts, and the part past 500 rows.
    group_name: str | None = None
    group_parts: Json | None = None
    part: int = 1
    rows: list[BatchRow]


class BatchLine(Out):
    id: str
    origin: str
    label: str
    created_at: str
    checked_at: str | None = None
    total: int
    finished: int
    waiting: int
    failed: int
    removed: int
    running: int
    pending: int
    stopped: Stopped | None = None
    group_name: str | None = None
    part: int = 1


class WaitingGroupLine(Out):
    """A group whose Ready when has not passed: its name, how many files it holds, and since when."""

    name: str
    held: int
    since: str


class WaitingGroups(Out):
    data: list[WaitingGroupLine]


class Retried(Out):
    retried: int
    # Rows a retry cannot change: a check's file that never ran.
    not_retryable: int


def _inputs(stored: DefinitionRow) -> Json:
    form = start_form(stored.definition, default_registry())
    props = cast(Json, (form or {}).get("schema") or {}).get("properties") if form else None
    if form is None or form.get("kind") != "form" or not props:
        raise Unprocessable(
            "This workflow's Request trigger has no inputs a file's columns could name.", code="no_start_form"
        )
    return cast(Json, props)


def _mapping(header: list[str], inputs: Json) -> tuple[dict[str, str], list[str]]:
    """Each column to the input it names, by key or by title, whatever the case."""
    names: dict[str, str] = {}
    for key, spec in inputs.items():
        names[key.strip().lower()] = key
        title = cast(Json, spec).get("title") if isinstance(spec, dict) else None
        if isinstance(title, str) and title.strip():
            names[title.strip().lower()] = key
    mapping = {h: names[h.strip().lower()] for h in header if h.strip().lower() in names}
    return mapping, [h for h in header if h not in mapping and h.strip()]


@router.post("/v1/workflows/{workflow_id}/batches", response_model=Envelope[DryRun | BatchStarted])
async def start_batch(rt: Rt, me: Me, workflow_id: str, body: BatchIn) -> JSONResponse:
    """Reads the file's rows and either shows how they map (dryRun) or writes the batch, whose rows the workflow
    worker starts a few at a time (202). No request transaction: the file is read from Files between the workflow
    read and the batch write, with none open."""
    stored = await startable(rt, me, workflow_id, None, body.mode)
    inputs = _inputs(stored)
    files = cast(FilesClient | None, rt.start_files)
    if files is None:
        raise ServiceUnavailable("A batch reads its file from Files, and this service has no Files URL.")
    tenant = current_tenant()
    try:
        info = await files.get(tenant, me.team_id, body.file_id)
        data = await files.read(tenant, me.team_id, body.file_id)
    except FileNotFound:
        raise NotFound(f"File {body.file_id}") from None
    header, rows = spreadsheet_rows(data, filename=info.name)
    if len(rows) > MAX_ROWS:
        raise Unprocessable(
            f"{info.name} has {len(rows)} rows. A batch takes up to {MAX_ROWS}. Split the file and start each part.",
            code="batch_too_many_rows",
            details={"rows": len(rows), "max": MAX_ROWS},
        )
    mapping, ignored = _mapping(header, inputs)
    if not mapping:
        titles = ", ".join(str(cast(Json, s).get("title") or k) for k, s in inputs.items())
        raise Unprocessable(
            f"No column in {info.name} names an input. Name the first row's columns {titles}.",
            code="batch_no_matching_columns",
        )
    mapped: list[Json] = []
    for n, r in enumerate(rows, start=1):
        try:
            mapped.append(checked_input(stored, {mapping[c]: v for c, v in r.items() if c in mapping and v != ""}))
        except Unprocessable as e:
            raise Unprocessable(
                f"Row {n} of {info.name}: {e.message} No run was started.",
                code=e.code,
                details={**(e.details or {}), "row": n},
            ) from e
    if body.dry_run:
        dry = {"rows": len(mapped), "mapping": mapping, "ignored": ignored, "sample": mapped[:SAMPLE]}
        return ok(dry)
    made = await Batches(rt.db).create(
        team_id=me.team_id,
        workflow_id=workflow_id,
        version=stored.version,
        mode=body.mode,
        file_id=body.file_id,
        file_name=info.name,
        created_by=started_by(me),
        rows=mapped,
    )
    return ok({"id": made.id, "total": made.total}, 202)


async def _batch(rt: Runtime, me: Principal, batch_id: str) -> BatchOut:
    found = await Batches(rt.db).get(batch_id)
    if found is None:
        raise NotFound(f"Batch {batch_id}")
    return found


def _status(r: BatchRowOut) -> str:
    if r.run_status:
        return r.run_status
    return r.row_status if r.row_status in ("failed", "removed") else "pending"


@router.get("/v1/workflows/{workflow_id}/batches", response_model=Envelope[ListResult[BatchLine]])
async def list_batches(rt: Rt, _: Reader, __: Tx, workflow_id: str, q: ListQuery) -> JSONResponse:
    """The workflow's batches, newest first unless `sortOrder` says otherwise, uploads and checks alike, each with its
    rows counted where they stand. 404 for a workflow the team does not hold."""
    if await definitions(rt).row(workflow_id, team=current_team()) is None:
        raise NotFound(f"Workflow {workflow_id}")
    page = await Batches(rt.db).of_workflow(workflow_id, q)
    lines = [
        {
            "id": b["id"], "origin": b["origin"], "label": b["file_name"], "createdAt": b["created_at"],
            "checkedAt": b["checked_at"], "total": b["total"], "finished": int(b["finished"]),
            "waiting": int(b["waiting"]), "failed": int(b["failed"]), "removed": int(b["removed"]),
            "running": int(b["running"]), "pending": int(b["pending"]),
            "stopped": {"reason": b["stopped_reason"], "at": b["stopped_at"]} if b["stopped_at"] else None,
            "groupName": b["group_name"], "part": b["part"],
        }
        for b in page["data"]
    ]  # fmt: skip
    return ok({**page, "data": lines})


@router.get("/v1/workflows/{workflow_id}/batches/waiting", response_model=Envelope[WaitingGroups])
async def waiting_groups(rt: Rt, _: Reader, __: Tx, workflow_id: str) -> JSONResponse:
    """The workflow's groups still waiting for their Ready when, oldest first, at most 200. 404 for a workflow the
    team does not hold."""
    if await definitions(rt).row(workflow_id, team=current_team()) is None:
        raise NotFound(f"Workflow {workflow_id}")
    groups = await WaitingFiles(rt.db).held(workflow_id)
    return ok({"data": [{"name": g.group_name, "held": g.held, "since": g.since} for g in groups]})


async def _shown_rows(rt: Runtime, me: Principal, batch_id: str) -> tuple[BatchOut, list[BatchRowOut]]:
    """The batch and its rows as people read them. A row's input, output and error are its run's data, so they are
    masked as the run's page masks them (aiStepsMaskPersonalData, on by default). The rows are read in one transaction,
    and platform-service is asked for the policy once it is closed."""
    async with isolation.request_transaction():
        batch = await _batch(rt, me, batch_id)
        rows = await Batches(rt.db).rows(batch_id)
    if not await ai_steps_gate.people_see_masked(rt, batch.team_id or None):
        return batch, rows
    shown = [r.model_copy(update={"input": masked(r.input), "output": masked(r.output), "error": masked(r.error)})
             for r in rows]  # fmt: skip
    return batch, shown


@router.get("/v1/batches/{batch_id}", response_model=Envelope[BatchView])
async def batch_page(rt: Rt, me: Reader, batch_id: str) -> JSONResponse:
    """The batch's counts and every row, failed first: what its page shows. No request transaction (`_shown_rows`)."""
    batch, rows = await _shown_rows(rt, me, batch_id)
    statuses = [_status(r) for r in rows]
    retryable = sum(r.run_status in ("failed", "cancelled") for r in rows)
    failed = sum(s in ("failed", "cancelled") for s in statuses)
    view = {
        "id": batch.id,
        "workflowId": batch.workflow_id,
        "origin": batch.origin,
        "fileName": batch.file_name,
        "watchId": batch.watch_id,
        "checkedAt": batch.checked_at,
        "mode": batch.mode,
        "total": batch.total,
        "finished": statuses.count("succeeded"),
        "failed": failed,
        "pending": statuses.count("pending"),
        "waiting": statuses.count("waiting"),
        "removed": statuses.count("removed"),
        "running": sum(s not in NOT_RUNNING for s in statuses),
        "retryable": retryable,
        "notRetryable": failed - retryable,
        "mayRetry": ACCESS.may(caller_of(me), "workflows", "decide", team=batch.team_id),
        "stopped": {"reason": batch.stopped_reason, "at": batch.stopped_at} if batch.stopped_at else None,
        "groupName": batch.group_name,
        "groupParts": batch.group_parts,
        "part": batch.part,
        "rows": [
            {
                "row": r.row, "attempt": r.attempt, "status": _status(r), "failureCode": r.failure_code,
                "reason": r.reason, "outcome": r.outcome,
                "output": r.output, "error": r.error, "runId": r.run_id, "input": r.input,
            }
            for r in rows
        ],
    }  # fmt: skip
    return ok(view)


@router.post("/v1/batches/{batch_id}/retry", status_code=202, response_model=Envelope[Retried])
async def retry_batch(rt: Rt, me: Me, batch_id: str) -> JSONResponse:
    """A new attempt for each failed row only; the worker starts them. A row that succeeded is never run again.
    No request transaction: the rows are queued for the workflow worker, and committing them with the request's reads
    would change when the worker sees them."""
    batch = await _batch(rt, me, batch_id)
    # Starting runs again is a decision on the workflow's runs, as a reviewer or admin makes, not an edit.
    can(caller_of(me), "workflows", "decide", team=batch.team_id or None, what=f"batch {batch_id}")
    retried, left = await Batches(rt.db).retry_failed(batch_id)
    return ok({"retried": retried, "notRetryable": left}, 202)


@router.get(
    "/v1/batches/{batch_id}/results.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}, "description": "One line per row"}},
)
async def batch_results(rt: Rt, me: Reader, batch_id: str) -> Response:
    """Every row as the page shows it, masked as the page masks it, one line each: row, input, status, outcome, run,
    error and output. Input and output are JSON, so a value holding a comma or a quote reads back as it was."""
    found, rows = await _shown_rows(rt, me, batch_id)
    out = io.StringIO()
    writer = csv.writer(out)
    if found.origin == "check":
        writer.writerows(check_csv(rows, found.group_name))
        return _csv(out.getvalue(), batch_id)
    writer.writerow(["row", "input", "status", "outcome", "runId", "error", "output"])

    def as_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False) if value is not None else ""

    for r in sorted(rows, key=lambda x: x.row):
        writer.writerow(
            [r.row, as_json(r.input), _status(r), r.outcome or "", r.run_id or "", r.error or "",
             as_json(r.output)]
        )  # fmt: skip
    return _csv(out.getvalue(), batch_id)


def _csv(text: str, batch_id: str) -> Response:
    name = f"results-{batch_id}.csv"
    return Response(text, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


# A spreadsheet runs a cell starting with one of these as a formula.
_FORMULA = ("=", "+", "-", "@")
CHECK_COLUMNS = ["file", "path", "version", "previousVersion", "status", "reason"]


def cell(value: Any) -> str:
    """One CSV cell: a list or object as JSON, nothing as empty, and text a spreadsheet would run as a formula kept
    as text by a leading apostrophe."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value).lower() if isinstance(value, bool) else str(value)
    return "'" + text if text.startswith(_FORMULA) else text


def field_columns(rows: list[BatchRowOut]) -> list[str]:
    """Every top-level key of the rows' run outputs, in the order first seen."""
    seen: dict[str, None] = {}
    for r in rows:
        output: Any = r.output
        if isinstance(output, dict):
            seen.update(dict.fromkeys(str(k) for k in cast(Json, output)))
    return list(seen)


def check_csv(rows: list[BatchRowOut], group: str | None = None) -> list[list[str]]:
    """A check's results: one line per file with its place, version and status, the reason a file did not run, and
    one column per field the runs returned. A grouped batch's lines start with its group's name, so a CSV of several
    groups' batches joined together still says which batch each line came from."""
    fields = field_columns(rows)
    lines = [(["group"] if group else []) + CHECK_COLUMNS + fields]
    for r in sorted(rows, key=lambda x: x.row):
        given = r.input
        returned: Any = r.output
        output = cast(Json, returned) if isinstance(returned, dict) else {}
        place = [given.get("name"), given.get("path"), given.get("version"), given.get("previousVersion")]
        why = r.reason or r.error
        lead = [cell(group)] if group else []
        lines.append(lead + [cell(v) for v in (*place, _status(r), why)] + [cell(output.get(f)) for f in fields])
    return lines
