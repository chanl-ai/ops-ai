"""Batches (c-535): start a workflow once per row of a CSV or Excel file, then follow it on its own page.

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
from pydantic import BaseModel, Field

from ops_engine import default_registry
from ops_engine.node_types import start_form
from ops_files_client import FileNotFound, FilesClient
from ops_ingest.parsers.spreadsheet import spreadsheet_rows
from ops_service_kit.errors import NotFound, ServiceUnavailable, Unprocessable
from ops_service_kit.http import Envelope

from ...store.batches import MAX_ROWS, Batches
from ...store.tenancy import current_tenant
from ..auth import Principal, principal, require_builder, started_by
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import Out
from .engine import startable

router = APIRouter(tags=["batches"])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040
SAMPLE = 5


class BatchIn(BaseModel):
    file_id: str = Field(alias="fileId", min_length=1, max_length=64)
    mode: Literal["live", "test"] = "live"
    dry_run: bool = Field(default=False, alias="dryRun")


class DryRun(Out):
    rows: int
    # Each column of the header that names an input, and the input's key.
    mapping: dict[str, str]
    # Columns that name no input, left out of every run.
    ignored: list[str]
    sample: list[dict[str, Any]]


class BatchStarted(Out):
    id: str
    total: int


class BatchRow(Out):
    row: int
    attempt: int
    # pending until its run starts, then the run's own status.
    status: str
    outcome: str | None = None
    output: Any = None
    error: str | None = None
    run_id: str | None = None
    input: dict[str, Any]


class Stopped(Out):
    reason: str
    at: str


class BatchView(Out):
    id: str
    workflow_id: str
    file_name: str
    mode: str
    total: int
    finished: int
    failed: int
    running: int
    pending: int
    stopped: Stopped | None = None
    rows: list[BatchRow]


class Retried(Out):
    retried: int


def _inputs(stored: dict[str, Any]) -> dict[str, Any]:
    form = start_form(stored["definition"], default_registry())
    props = cast(dict[str, Any], (form or {}).get("schema") or {}).get("properties") if form else None
    if form is None or form.get("kind") != "form" or not props:
        raise Unprocessable(
            "This workflow's Request trigger has no inputs a file's columns could name.", code="no_start_form"
        )
    return cast(dict[str, Any], props)


def _mapping(header: list[str], inputs: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """Each column to the input it names, by key or by title, whatever the case."""
    names: dict[str, str] = {}
    for key, spec in inputs.items():
        names[key.strip().lower()] = key
        title = cast(dict[str, Any], spec).get("title") if isinstance(spec, dict) else None
        if isinstance(title, str) and title.strip():
            names[title.strip().lower()] = key
    mapping = {h: names[h.strip().lower()] for h in header if h.strip().lower() in names}
    return mapping, [h for h in header if h not in mapping and h.strip()]


@router.post("/v1/workflows/{workflow_id}/batches", response_model=Envelope[DryRun | BatchStarted])
async def start_batch(rt: Rt, me: Me, workflow_id: str, body: BatchIn) -> JSONResponse:
    """Reads the file's rows and either shows how they map (dryRun) or writes the batch, whose rows the workflow
    worker starts a few at a time (202)."""
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
        titles = ", ".join(str(cast(dict[str, Any], s).get("title") or k) for k, s in inputs.items())
        raise Unprocessable(
            f"No column in {info.name} names an input. Name the first row's columns {titles}.",
            code="batch_no_matching_columns",
        )
    mapped = [{mapping[c]: v for c, v in r.items() if c in mapping and v != ""} for r in rows]
    if body.dry_run:
        dry = {"rows": len(mapped), "mapping": mapping, "ignored": ignored, "sample": mapped[:SAMPLE]}
        return ok(dry)
    made = await Batches(rt.db).create(
        team_id=me.team_id,
        workflow_id=workflow_id,
        version=int(stored["version"]),
        mode=body.mode,
        file_id=body.file_id,
        file_name=info.name,
        created_by=started_by(me),
        rows=mapped,
    )
    return ok({"id": made["id"], "total": made["total"]}, 202)


async def _batch(rt: Runtime, me: Principal, batch_id: str) -> dict[str, Any]:
    found = await Batches(rt.db).get(batch_id)
    if found is None:
        raise NotFound(f"Batch {batch_id}")
    return found


def _status(r: dict[str, Any]) -> str:
    return str(r["run_status"]) if r["run_status"] else "pending"


@router.get("/v1/batches/{batch_id}", response_model=Envelope[BatchView])
async def batch_page(rt: Rt, me: Me, batch_id: str) -> JSONResponse:
    """The batch's counts and every row, failed first: what its page shows."""
    batch = await _batch(rt, me, batch_id)
    rows = await Batches(rt.db).rows(batch_id)
    statuses = [_status(r) for r in rows]
    view = {
        "id": batch["id"],
        "workflowId": batch["workflow_id"],
        "fileName": batch["file_name"],
        "mode": batch["mode"],
        "total": batch["total"],
        "finished": statuses.count("succeeded"),
        "failed": sum(s in ("failed", "cancelled") for s in statuses),
        "pending": statuses.count("pending"),
        "running": sum(s not in ("succeeded", "failed", "cancelled", "pending") for s in statuses),
        "stopped": {"reason": batch["stopped_reason"], "at": batch["stopped_at"]} if batch["stopped_at"] else None,
        "rows": [
            {
                "row": r["row"], "attempt": r["attempt"], "status": _status(r), "outcome": r["outcome"],
                "output": r["output"], "error": r["error"], "runId": r["run_id"], "input": r["input"],
            }
            for r in rows
        ],
    }  # fmt: skip
    return ok(view)


@router.post("/v1/batches/{batch_id}/retry", status_code=202, response_model=Envelope[Retried])
async def retry_batch(rt: Rt, me: Me, batch_id: str) -> JSONResponse:
    """A new attempt for each failed row only; the worker starts them. A row that succeeded is never run again."""
    batch = await _batch(rt, me, batch_id)
    require_builder(me, area="workflows", team_id=str(batch["team_id"]), action="edit", what=f"batch {batch_id}")
    return ok({"retried": await Batches(rt.db).retry_failed(batch_id)}, 202)


@router.get(
    "/v1/batches/{batch_id}/results.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}, "description": "One line per row"}},
)
async def batch_results(rt: Rt, me: Me, batch_id: str) -> Response:
    """Every row as the page shows it, one line each: row, status, outcome, run, error and output."""
    await _batch(rt, me, batch_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["row", "status", "outcome", "runId", "error", "output"])
    for r in sorted(await Batches(rt.db).rows(batch_id), key=lambda x: int(x["row"])):
        output = json.dumps(r["output"], ensure_ascii=False) if r["output"] is not None else ""
        writer.writerow([r["row"], _status(r), r["outcome"] or "", r["run_id"] or "", r["error"] or "", output])
    name = f"results-{batch_id}.csv"
    return Response(
        out.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )
