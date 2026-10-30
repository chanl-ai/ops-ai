"""Starting one run per row of a CSV (c-535), by failure mode: a dry run that starts runs, or maps a column to no input
without saying so; a file over 500 rows, or with a header naming none of the inputs, that starts runs with empty
inputs; a row started twice when two worker ticks race; Retry failed rows starting a row that succeeded; a batch that
keeps starting rows after the team's model budget ran out; results that cannot be taken away. Real routes on the app
with its own database; Files is faked at its routes and the worker's batch tick is called directly."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from httpx import AsyncClient

from ops_agents.api.batches import start_pending
from ops_agents.api.engine_runs import start_run
from ops_agents.store.batches import run_key
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import DefinitionStore, RunStore
from ops_engine.store.tables import engine_runs
from tests.api.test_forms import flow, runs_of
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, TENANT
from tests.engine.test_run_starts import Files, files_client

WID = "claim_follow_up"
INPUTS = {
    "type": "object",
    "required": ["claim_ref"],
    "properties": {
        "claim_ref": {"type": "string", "title": "Claim reference"},
        "policy": {"type": "string", "title": "Policy number"},
        "email": {"type": "string", "title": "Contact email"},
    },
}


def csv(rows: int, header: str = "claim_ref,Policy number,email,adjuster") -> bytes:
    lines = [header] + [f"HM-{23000 + i},P-{77000 + i},c{i}@example.com,K. Ito" for i in range(rows)]
    return ("\n".join(lines) + "\n").encode()


async def ready(c: AsyncClient, files: Files, body: bytes, name: str = "claims-oct.csv") -> str:
    """The workflow live, and the file in Files, scanned clean, in team_ops."""
    made = await c.post("/v1/workflows/definitions", json={"definition": flow(WID, INPUTS)}, headers=BUILDER)
    if made.status_code == 201:
        published = await c.post(f"/v1/workflows/definitions/{WID}/publish-requests", json={}, headers=BUILDER)
        assert published.status_code == 201, published.text
    fid = f"file_{len(files.stored) + 1}"
    files.stored[fid] = {
        "id": fid, "name": name, "mime": "text/csv", "size": len(body), "digest": "d", "purpose": "case_attachment",
        "team": "team_ops", "uploadedBy": "james@harborpine.example", "scan": {"status": "clean"}, "bytes": body,
    }  # fmt: skip
    return fid


def wired(c: AsyncClient) -> tuple[Any, Files]:
    rt: Any = c._transport.app.state.runtime  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue, reportPrivateUsage, reportUnknownMemberType]
    files = Files()
    rt.start_files = files_client(files)
    return rt, files  # pyright: ignore[reportUnknownVariableType]


async def batch(c: AsyncClient, fid: str, *, dry: bool = False) -> Any:
    return await c.post(
        f"/v1/workflows/{WID}/batches", json={"fileId": fid, "mode": "live", "dryRun": dry}, headers=BUILDER
    )


async def tick(rt: Any) -> int:
    return await start_pending(rt.db, limit=50)


async def test_a_dry_run_maps_the_header_shows_the_first_rows_and_starts_nothing(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    _, files = wired(c)
    fid = await ready(c, files, csv(7))
    r = await batch(c, fid, dry=True)
    assert r.status_code == 200, r.text
    dry = r.json()["data"]
    assert dry["rows"] == 7 and dry["ignored"] == ["adjuster"], dry
    assert dry["mapping"] == {"claim_ref": "claim_ref", "Policy number": "policy", "email": "email"}, dry["mapping"]
    assert len(dry["sample"]) == 5 and dry["sample"][0] == {
        "claim_ref": "HM-23000",
        "policy": "P-77000",
        "email": "c0@example.com",
    }, dry["sample"]
    assert await runs_of(c, WID) == []


async def test_too_many_rows_or_a_header_naming_no_input_is_refused_before_any_run(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    rt, files = wired(c)
    big = await batch(c, await ready(c, files, csv(501)))
    stray = await batch(c, await ready(c, files, csv(3, header="ref,number,mail,who"), name="export.csv"))
    assert big.status_code == 422 and big.json()["error"]["code"] == "batch_too_many_rows", big.text
    assert "501" in big.json()["error"]["message"] and "500" in big.json()["error"]["message"], big.text
    assert stray.status_code == 422 and stray.json()["error"]["code"] == "batch_no_matching_columns", stray.text
    assert "Claim reference" in stray.json()["error"]["message"], "the refusal names the inputs the header could name"
    await tick(rt)
    assert await runs_of(c, WID) == []


async def test_a_row_another_worker_started_is_adopted_and_retry_starts_only_the_failed_rows(stack: Stack) -> None:  # noqa: F811
    """Two workers reaching one row cannot be raced on this test database (one shared connection), so the lost race
    is set up by hand: another worker started row 1's run under its key and stopped before recording it."""
    c, _ = stack
    rt, files = wired(c)
    started = await batch(c, await ready(c, files, csv(7)))
    assert started.status_code == 202, started.text
    bid = started.json()["data"]["id"]
    with tenant_scope(TENANT):
        stored = await DefinitionStore(EngineTransactions(rt.db)).get(WID, 1)
        assert stored is not None
        other, _ = await start_run(
            RunStore(EngineTransactions(rt.db)), stored, team_id="team_ops", mode="live", input={},
            run_key=run_key(bid, 1, 1), created_by="james@harborpine.example", started_via="start:batch",
        )  # fmt: skip
    await tick(rt)
    await tick(rt)
    runs = await runs_of(c, WID)
    assert len(runs) == 7, "the row another worker started is adopted, and a second tick starts nothing again"
    rows = (await c.get(f"/v1/batches/{bid}", headers=BUILDER)).json()["data"]["rows"]
    assert next(r for r in rows if r["row"] == 1)["runId"] == other["id"], rows
    one = (await c.get(f"/v1/runs/{runs[0].get('runId') or runs[0]['id']}", headers=BUILDER)).json()["data"]
    assert one["startedBy"]["via"] == {"kind": "start", "id": "batch", "name": "batch"}, one["startedBy"]
    failed_ids = [r.get("runId") or r["id"] for r in runs[:2]]
    async with rt.db.begin() as conn:
        await conn.execute(
            engine_runs.update()
            .where(engine_runs.c.id.in_(failed_ids))
            .values(status="failed", error="Policy not found")
        )
    page = (await c.get(f"/v1/batches/{bid}", headers=BUILDER)).json()["data"]
    assert (page["total"], page["failed"]) == (7, 2) and [r["status"] for r in page["rows"][:2]] == ["failed"] * 2, page
    retried = await c.post(f"/v1/batches/{bid}/retry", headers=BUILDER)
    assert retried.status_code == 202 and retried.json()["data"]["retried"] == 2, retried.text
    await tick(rt)
    assert len(await runs_of(c, WID)) == 9, "only the two failed rows run again"


async def test_a_model_budget_refusal_stops_the_batch_and_its_page_says_so(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    rt, files = wired(c)
    bid = (await batch(c, await ready(c, files, csv(60)))).json()["data"]["id"]
    assert await tick(rt) == 50
    [first] = (await runs_of(c, WID))[-1:]
    async with rt.db.begin() as conn:
        await conn.execute(
            engine_runs.update()
            .where(engine_runs.c.id == (first.get("runId") or first["id"]))
            .values(status="failed", error="budget_exhausted: the team's model budget for October is spent")
        )
    assert await tick(rt) == 0, "no row starts after the budget ran out"
    page = (await c.get(f"/v1/batches/{bid}", headers=BUILDER)).json()["data"]
    assert page["stopped"] and "budget" in page["stopped"]["reason"], page


async def test_the_results_download_lists_every_row_with_its_status(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    rt, files = wired(c)
    bid = (await batch(c, await ready(c, files, csv(3)))).json()["data"]["id"]
    await tick(rt)
    r = await c.get(f"/v1/batches/{bid}/results.csv", headers=BUILDER)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv"), r.text
    lines = r.text.strip().splitlines()
    assert lines[0].split(",")[:3] == ["row", "status", "outcome"] and len(lines) == 4, lines
    async with rt.db.connect() as conn:
        n = await conn.scalar(
            sa.select(sa.func.count()).select_from(engine_runs).where(engine_runs.c.workflow_id == WID)
        )
    assert n == 3
