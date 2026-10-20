"""Runs: written with their start work row in one transaction, read by the run list and detail."""

from __future__ import annotations

from typing import Any, ClassVar, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from ops_store import Guarantee

from .clock import db_now, now_iso
from .tables import ENGINE_BUILD, engine_definitions, engine_runs, engine_steps, engine_work
from .tx import Transactions
from .work import WorkQueue

TERMINAL = ("succeeded", "failed", "cancelled")
# A run that another run's step started names that run in created_by: `run:<parent id>`.
CHILD_PREFIX = "run:"


class DefinitionGoneError(LookupError):
    """The version a run would pin was deleted before the run could be written."""


class NotLiveError(PermissionError):
    """A live run would pin a version that is not live (a draft, a superseded version, or a paused workflow's), or any
    run would pin a version of an archived workflow (stage `archived`)."""

    def __init__(self, stage: str) -> None:
        super().__init__(f"the version is {stage}, not live")
        self.stage = stage


class RunStore:
    # A run and its start row commit together (TRANSACTION); a repeated run key loses on the unique key (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.CAS})

    def __init__(self, tx: Transactions) -> None:
        self.tx = tx

    async def create(self, run: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Writes the run (status queued) and its start work row; a run with the same key is returned instead.
        A live run is refused (NotLiveError) unless the version it pins is live, read under the same lock a pause
        takes, so a pause and a start cannot both pass. Returns (run, created)."""
        at = now_iso()
        values = {**run, "tenant_id": self.tx.tenant(), "status": "queued", "created_at": at, "updated_at": at}
        d = engine_definitions
        try:
            async with self.tx.tenant_tx() as c:
                # The pinned version, locked until the run commits: a delete of the workflow waits for this start
                # (and then sees its run), or ran first and the start finds the version gone.
                pinned = await c.execute(
                    sa.select(d.c.stage, d.c.archived_at)
                    .where(
                        d.c.tenant_id == values["tenant_id"],
                        d.c.workflow_id == run["workflow_id"],
                        d.c.version == run["version"],
                        d.c.digest == run["digest"],
                    )
                    .with_for_update()
                )
                found = pinned.first()
                if found is None:
                    raise DefinitionGoneError(f"{run['workflow_id']} version {run['version']} no longer exists")
                if found.archived_at is not None:
                    raise NotLiveError("archived")
                if run["mode"] == "live" and found.stage != "live":
                    raise NotLiveError(str(found.stage))
                await c.execute(engine_runs.insert().values(**values))
                await c.execute(
                    engine_work.insert().values(
                        tenant_id=values["tenant_id"],
                        run_id=run["id"],
                        kind="start",
                        payload=None,
                        dedupe_key=f"start:{run['id']}",
                        status="queued",
                        build=ENGINE_BUILD,
                        available_at=db_now(c),
                        attempts=0,
                        created_at=at,
                    )
                )
        except IntegrityError:
            found = await self.by_key(str(run["workflow_id"]), str(run["run_key"]))
            if found is None:
                raise
            return found, False
        return await self.get(str(run["id"])) or values, True

    async def by_key(self, workflow_id: str, run_key: str) -> dict[str, Any] | None:
        q = engine_runs.select().where(
            engine_runs.c.tenant_id == self.tx.tenant(),
            engine_runs.c.workflow_id == workflow_id,
            engine_runs.c.run_key == run_key,
        )
        async with self.tx.tenant_tx() as c:
            row = (await c.execute(q)).mappings().first()
        return dict(row) if row else None

    async def get(self, run_id: str) -> dict[str, Any] | None:
        q = engine_runs.select().where(engine_runs.c.id == run_id, engine_runs.c.tenant_id == self.tx.tenant())
        async with self.tx.tenant_tx() as c:
            row = (await c.execute(q)).mappings().first()
        return dict(row) if row else None

    async def many(self, run_ids: list[str]) -> list[dict[str, Any]]:
        """The tenant's runs among `run_ids`, in one query (a step's started children, up to its item limit)."""
        if not run_ids:
            return []
        q = engine_runs.select().where(engine_runs.c.id.in_(run_ids), engine_runs.c.tenant_id == self.tx.tenant())
        async with self.tx.tenant_tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def list(
        self, *, workflow_id: str | None = None, status: str | None = None, team_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        q = engine_runs.select().where(engine_runs.c.tenant_id == self.tx.tenant())
        if workflow_id:
            q = q.where(engine_runs.c.workflow_id == workflow_id)
        if status:
            q = q.where(engine_runs.c.status == status)
        if team_id:
            q = q.where(engine_runs.c.team_id == team_id)
        q = q.order_by(engine_runs.c.created_at.desc()).limit(limit)
        async with self.tx.tenant_tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def page(
        self,
        *,
        workflow_id: str | None = None,
        statuses: list[str] | None = None,
        team_id: str | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        """One page of runs, newest first, each with `workflow_name`, plus the total that matches and the count per
        status. The status counts leave the status filter out, so a filter chip shows how many runs choosing it would
        list."""
        base = [engine_runs.c.tenant_id == self.tx.tenant()]
        if workflow_id:
            base.append(engine_runs.c.workflow_id == workflow_id)
        if team_id:
            base.append(engine_runs.c.team_id == team_id)
        where = [*base, engine_runs.c.status.in_(statuses)] if statuses else base
        # Each row carries its workflow version's display name, so a list names the workflow, not its id.
        named = engine_runs.outerjoin(
            engine_definitions,
            sa.and_(
                engine_definitions.c.tenant_id == engine_runs.c.tenant_id,
                engine_definitions.c.workflow_id == engine_runs.c.workflow_id,
                engine_definitions.c.version == engine_runs.c.version,
            ),
        )
        rows_q = (
            sa.select(*engine_runs.c, engine_definitions.c.name.label("workflow_name"))
            .select_from(named)
            .where(*where)
            .order_by(engine_runs.c.created_at.desc(), engine_runs.c.id)
        )
        total_q = sa.select(sa.func.count()).select_from(engine_runs).where(*where)
        by_status_q = sa.select(engine_runs.c.status, sa.func.count()).where(*base).group_by(engine_runs.c.status)
        async with self.tx.tenant_tx() as c:
            rows = [dict(r) for r in (await c.execute(rows_q.offset(offset).limit(limit))).mappings()]
            total = int((await c.execute(total_q)).scalar_one())
            by_status = {str(k): int(n) for k, n in (await c.execute(by_status_q)).all()}
        return rows, total, by_status

    async def update(self, run_id: str, *, generation: int | None = None, **values: Any) -> None:
        """`generation`: the writing worker's lease generation, checked in this transaction, so a superseded worker's
        status write is refused. A cancelled run is never written again: a pass still running when it was cancelled
        cannot move it back to running, waiting or succeeded."""
        async with self.tx.tenant_tx() as c:
            await self.tx.check_fence(c, run_id, generation)
            await c.execute(
                engine_runs.update()
                .where(engine_runs.c.id == run_id, engine_runs.c.status != "cancelled")
                .values(**values, updated_at=now_iso())
            )

    async def finish(
        self, run_id: str, *, generation: int | None, failed: bool, outcome: str, output: Any, error: str | None
    ) -> str:
        """Records the End the run's graph reached and returns the status written. A failure End fails the run. A
        run whose graph ended while runs it started are still going is not done: it reads waiting while one of them
        waits on a person, else running, and succeeds when the last one ends (settle_parents)."""
        r = engine_runs
        at = now_iso()
        async with self.tx.tenant_tx() as c:
            await self.tx.check_fence(c, run_id, generation)
            mine = sa.and_(r.c.id == run_id, r.c.tenant_id == self.tx.tenant(), r.c.status != "cancelled")
            await c.execute(sa.select(r.c.id).where(mine).with_for_update())
            status = "failed" if failed else (await self._children_left(c, run_id) or "succeeded")
            done = status in TERMINAL
            await c.execute(
                r.update()
                .where(mine)
                .values(
                    status=status,
                    outcome=outcome,
                    output=output,
                    error=error,
                    waiting=None,
                    finished_at=at if done else None,
                    updated_at=at,
                )
            )
        return status

    async def settle_parents(self, run: dict[str, Any]) -> None:
        """After `run` changed status: the run that started it, once its own graph has ended (its outcome is set),
        takes the status its unfinished runs leave it, and succeeds when none is left; then the same for that run's
        parent. The parent row is locked, so two runs ending at once cannot both leave it unsettled. A parent paused at
        a Run workflow step waiting for its children (c-263) is woken instead: one resume per change of a child's
        status, keyed so settling twice queues it once, naming the step rather than the pause."""
        r = engine_runs
        here = run
        while str(here.get("created_by") or "").startswith(CHILD_PREFIX):
            parent_id = str(here["created_by"])[len(CHILD_PREFIX) :]
            at = now_iso()
            wake: tuple[str, str, str | None] | None = None
            async with self.tx.tenant_tx() as c:
                mine = sa.and_(r.c.id == parent_id, r.c.tenant_id == self.tx.tenant())
                query = sa.select(r.c.status, r.c.outcome, r.c.waiting).where(mine).with_for_update()
                found = (await c.execute(query)).first()
                if found is None or found.status in TERMINAL:
                    return
                if found.outcome is None:
                    waiting = cast(dict[str, Any], found.waiting or {})
                    waits = cast(dict[str, Any], waiting.get("payload") or {})
                    if waits.get("kind") != "children":
                        return
                    child = str(here["id"])
                    mine_child = sa.and_(r.c.id == child, r.c.tenant_id == self.tx.tenant())
                    now = await c.scalar(sa.select(r.c.status).where(mine_child))
                    # The pause it wakes, by interrupt id: a wake for one pass of the step never resumes a later one.
                    pause = cast(str | None, waiting.get("interruptId"))
                    wake = (f"children:{parent_id}:{child}:{now}", str(waits.get("node")), pause)
                else:
                    status = await self._children_left(c, parent_id) or "succeeded"
                    if status == found.status:
                        return
                    finished = at if status in TERMINAL else None
                    await c.execute(r.update().where(mine).values(status=status, finished_at=finished, updated_at=at))
            if wake is not None:
                key, node, interrupt_id = wake
                payload = {"resume": {"child": str(here["id"])}, "node": node, "interruptId": interrupt_id}
                await WorkQueue(self.tx, owner="settle", ttl=0).enqueue(parent_id, "resume", key, payload)
                return
            parent = await self.get(parent_id)
            if parent is None:
                return
            here = parent

    async def children(self, parent_run_id: str, key_prefix: str, *, outputs: bool = False) -> list[dict[str, Any]]:
        """The runs `parent_run_id` started under keys beginning `key_prefix`, in one read on the parent index, each
        with the item index its key ends with, in item order (c-263). Outputs are read only when asked: a step waiting
        on many children reads their states on every wake and their outputs once, when it goes on."""
        r = engine_runs
        columns = [r.c.id, r.c.status, r.c.outcome, r.c.run_key, *([r.c.output] if outputs else [])]
        q = sa.select(*columns).where(
            r.c.tenant_id == self.tx.tenant(),
            r.c.created_by == f"{CHILD_PREFIX}{parent_run_id}",
            r.c.run_key.startswith(key_prefix, autoescape=True),
        )
        async with self.tx.tenant_tx() as c:
            rows = (await c.execute(q)).mappings().all()
        found = [
            {
                "index": int(str(row["run_key"])[len(key_prefix) :]),
                "runId": str(row["id"]),
                "status": str(row["status"]),
                "outcome": row["outcome"],
                "output": row["output"] if outputs else None,
            }
            for row in rows
        ]
        return sorted(found, key=lambda x: x["index"])

    async def _children_left(self, c: Any, run_id: str) -> str | None:
        """waiting when a run this one started waits on a person, running when one is otherwise unfinished. Each is
        an EXISTS on (tenant_id, created_by, status), so a parent with many runs is not reread on every change."""
        r = engine_runs
        mine = sa.and_(r.c.tenant_id == self.tx.tenant(), r.c.created_by == f"{CHILD_PREFIX}{run_id}")
        for status, among in (("waiting", ["waiting"]), ("running", ["queued", "running"])):
            if await c.scalar(sa.select(sa.exists().where(mine, r.c.status.in_(among)))):
                return status
        return None

    async def cancel(self, run_id: str, *, reason: str = "by_user") -> tuple[dict[str, Any] | None, bool]:
        """Cancels a run that has not ended: status cancelled with `reason` as its outcome, its waiting step cleared
        (which withdraws its review), and its queued work dropped so no worker starts it. A worker already in a pass
        finishes and journals the step under way, and the next step's journal row is refused (SqlJournal.begin).
        Returns (run, changed); changed is False for a run that had already ended, which is returned as it is."""
        at = now_iso()
        r, w = engine_runs, engine_work
        async with self.tx.tenant_tx() as c:
            mine = sa.and_(r.c.id == run_id, r.c.tenant_id == self.tx.tenant())
            found = (await c.execute(sa.select(r.c.status).where(mine).with_for_update())).first()
            if found is None:
                return None, False
            changed = found.status not in TERMINAL
            if changed:
                await c.execute(
                    r.update()
                    .where(mine)
                    .values(status="cancelled", outcome=reason, waiting=None, finished_at=at, updated_at=at)
                )
                await c.execute(
                    w.update()
                    .where(w.c.run_id == run_id, w.c.tenant_id == self.tx.tenant(), w.c.status == "queued")
                    .values(status="done", error=f"run cancelled ({reason})")
                )
        return await self.get(run_id), changed

    async def steps(self, run_id: str) -> list[dict[str, Any]]:
        """Every attempt of every node, in the order they started."""
        q = (
            engine_steps.select()
            .where(engine_steps.c.run_id == run_id, engine_steps.c.tenant_id == self.tx.tenant())
            .order_by(engine_steps.c.started_at, engine_steps.c.node_id, engine_steps.c.attempt)
        )
        async with self.tx.tenant_tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def steps_of(self, run_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """steps() for each of these runs in one query, so a list of runs does not read them one run at a time."""
        if not run_ids:
            return {}
        s = engine_steps
        q = (
            s.select()
            .where(s.c.run_id.in_(run_ids), s.c.tenant_id == self.tx.tenant())
            .order_by(s.c.started_at, s.c.node_id, s.c.attempt)
        )
        out: dict[str, list[dict[str, Any]]] = {r: [] for r in run_ids}
        async with self.tx.tenant_tx() as c:
            for row in (await c.execute(q)).mappings():
                out[str(row["run_id"])].append(dict(row))
        return out

    async def work(self, run_id: str) -> list[dict[str, Any]]:
        q = (
            engine_work.select()
            .where(engine_work.c.run_id == run_id, engine_work.c.tenant_id == self.tx.tenant())
            .order_by(engine_work.c.id)
        )
        async with self.tx.tenant_tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def resumes(self, run_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Each run's decided Human Tasks, oldest first: the resume payloads the decide route queued, for every run in
        one query, so a list of runs does not read them one run at a time."""
        if not run_ids:
            return {}
        w = engine_work
        q = (
            sa.select(w.c.run_id, w.c.payload)
            .where(w.c.tenant_id == self.tx.tenant(), w.c.kind == "resume", w.c.run_id.in_(run_ids))
            .order_by(w.c.created_at, w.c.id)
        )
        out: dict[str, list[dict[str, Any]]] = {}
        async with self.tx.tenant_tx() as c:
            for run_id, payload in (await c.execute(q)).all():
                out.setdefault(str(run_id), []).append(dict(payload or {}))
        return out
