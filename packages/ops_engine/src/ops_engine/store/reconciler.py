"""The run reconciler (c-561): finds workflow runs nothing is behind and gives each a clear state.

A run moves only when a worker claims one of its work rows, so a run that reads Queued, Running or Waiting with no row
a worker can claim or holds never moves again. The reconciler reads every tenant's unfinished runs past row-level
security (`RECONCILE_RUNS`, read-only), then changes each finding inside its own tenant, as a worker's pass does:

| Finding | What it does |
|---|---|
| Queued or Running, no work row at all (one due later counts), unchanged for `quiet_s` | Stuck |
| Waiting, no work row, nothing live named: not a review, not children still unfinished | Stuck |
| A work row whose claim lapsed more than `max_lapses` times (its worker died on it) | Stuck, row set aside |
| Work rows queued only for another `ENGINE_BUILD`, which no worker of this build claims | Stuck, row set aside |
| A child Queued or Running whose steps ran past 24 h, its parent's step setting no timeoutHours | Child failed |

A child that ran too long is failed and its parent woken by its step's timeout, which leaves by the timeout port.

Stuck keeps the run's checkpoints and journal: Retry queues it again from its last recorded step. Time a child waited
for a person, an event or a timer is not counted toward its limit: only its steps' running time is.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import sqlalchemy as sa

from .clock import now_iso
from .runs import CHILD_PREFIX, TERMINAL, RunStore
from .tables import ENGINE_BUILD, engine_definitions, engine_runs, engine_steps, engine_work
from .tx import RECONCILE_RUNS, Transactions
from .work import MAX_LAPSES, WorkQueue

QUIET_S = 600.0
CHILD_LIMIT_S = 24 * 3600.0

NOTHING_BEHIND = "Nothing is working on this run: no worker has picked it up for 10 minutes."
NOTHING_LIVE = "It waits for nothing that can still wake it."
OLD_BUILD = "It waits for an older version of the workflow engine, which no worker runs."
TOO_LONG = "ran past its time limit"


def lapsed(n: int, running: str | None = None, after: str | None = None) -> str:
    """Names the step the deaths happened in when one is recorded as running, else the last step it finished."""
    if running:
        return f"Its worker stopped {n} times while running {running}."
    if after:
        return f"Its worker stopped {n} times after {after}."
    return f"Its worker stopped {n} times while running it."


def _deaths(row: Any, now_s: float) -> int:
    """Each lapse is a claim whose worker died before the row was claimed again; a claim that has lapsed and not been
    claimed since (the claim filter stops at MAX_LAPSES) is one more death that `lapses` has not counted yet."""
    n = int(row.lapses or 0)
    if row.status == "claimed" and row.lease_expires_at is not None and float(row.lease_expires_at) <= now_s:
        n += 1
    return n


def _alive(row: Any, now_s: float) -> bool:
    return row.status == "claimed" and row.lease_expires_at is not None and float(row.lease_expires_at) > now_s


@dataclass(frozen=True)
class Finding:
    tenant_id: str
    run_id: str
    # stuck: mark the run Stuck; child: fail the child and wake its parent's timeout; ended: a run whose graph ended
    # takes the status the runs it started leave it.
    action: str
    reason: str
    # For a child: its parent's run id and the step and iteration it waits at.
    parent: dict[str, Any] = field(default_factory=lambda: {})
    # Work rows to set aside so no worker claims them before Retry.
    set_aside: bool = False


def _when(stamp: str | None) -> datetime | None:
    """A stored timestamp, or None when it is missing or unreadable: one bad row must not stop the pass for every
    tenant, so a run whose time cannot be read is left alone rather than judged."""
    if not stamp:
        return None
    try:
        at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def _age_s(stamp: str | None, now: datetime) -> float:
    at = _when(stamp)
    return (now - at).total_seconds() if at is not None else 0.0


async def _where(tx: Transactions, run: Any) -> tuple[str | None, str | None]:
    """The step a run's worker was running when it died, else the last step it finished, by the names its version
    gives them. Read only for a run being marked Stuck, so the scan of every active run stays one query per table."""
    s, d = engine_steps, engine_definitions
    async with tx.system_tx(RECONCILE_RUNS) as c:
        steps = (
            await c.execute(
                sa.select(s.c.node_id, s.c.finished_at, s.c.started_at)
                .where(s.c.tenant_id == run.tenant_id, s.c.run_id == run.id)
                .order_by(s.c.started_at.desc())
            )
        ).all()
        definition = await c.scalar(
            sa.select(d.c.definition).where(
                d.c.tenant_id == run.tenant_id, d.c.workflow_id == run.workflow_id, d.c.version == run.version
            )
        )
    nodes = cast(list[dict[str, Any]], cast(dict[str, Any], definition or {}).get("nodes") or [])
    names = {str(n.get("id")): str(n.get("name") or n.get("id")) for n in nodes}
    running = next((x.node_id for x in steps if x.finished_at is None), None)
    finished = [x for x in steps if x.finished_at is not None]
    after = max(finished, key=lambda x: str(x.finished_at)).node_id if finished else None
    if running:
        return names.get(running, running), None
    return None, (names.get(after, after) if after else None)


async def find(
    tx: Transactions,
    *,
    quiet_s: float = QUIET_S,
    max_lapses: int = MAX_LAPSES,
    child_limit_s: float = CHILD_LIMIT_S,
    build: str = ENGINE_BUILD,
) -> list[Finding]:
    """Every tenant's runs that need a state of their own, read past the tenant and changed by `settle` in it."""
    r, w, s = engine_runs, engine_work, engine_steps
    now = datetime.now(UTC)
    now_s = time.time()
    found: list[Finding] = []
    async with tx.system_tx(RECONCILE_RUNS) as c:
        active = (
            await c.execute(
                sa.select(
                    r.c.id,
                    r.c.tenant_id,
                    r.c.status,
                    r.c.waiting,
                    r.c.updated_at,
                    r.c.created_by,
                    r.c.workflow_id,
                    r.c.version,
                    r.c.outcome,
                ).where(
                    sa.or_(
                        r.c.status.in_(("queued", "running", "waiting")),
                        # A run marked Stuck while its graph had ended and the runs it started still went on (#14).
                        sa.and_(r.c.status == "stuck", r.c.outcome.is_not(None)),
                    )
                )
            )
        ).all()
        if not active:
            return found
        ids = [a.id for a in active]
        work = (
            await c.execute(
                sa.select(w.c.run_id, w.c.status, w.c.build, w.c.lapses, w.c.lease_expires_at).where(
                    w.c.run_id.in_(ids), w.c.status.in_(("queued", "claimed"))
                )
            )
        ).all()
        child_ids = [a.id for a in active if str(a.created_by or "").startswith(CHILD_PREFIX)]
        parents = {str(a.created_by)[len(CHILD_PREFIX) :] for a in active if a.id in child_ids}
        # Every child of a waiting parent, ended or not, to tell a parent with unfinished children from one none wakes.
        # A run whose own graph ended (its outcome is set) waits only for the runs it started, whatever its status.
        waiting_parents = [a.id for a in active if a.status == "waiting" or a.outcome is not None]
        kids = (
            await c.execute(
                sa.select(r.c.created_by, r.c.status).where(
                    r.c.created_by.in_([f"{CHILD_PREFIX}{p}" for p in waiting_parents])
                )
            )
        ).all()
        parent_rows = {
            row.id: row
            for row in (
                await c.execute(sa.select(r.c.id, r.c.status, r.c.waiting).where(r.c.id.in_(list(parents))))
            ).all()
        }
        steps = (
            await c.execute(
                sa.select(s.c.run_id, s.c.status, s.c.effects, s.c.started_at, s.c.finished_at).where(
                    s.c.run_id.in_(child_ids)
                )
            )
        ).all()
    rows_of: dict[str, list[Any]] = {}
    for row in work:
        rows_of.setdefault(row.run_id, []).append(row)
    unfinished_children: set[str] = {str(k.created_by)[len(CHILD_PREFIX) :] for k in kids if k.status not in TERMINAL}
    ran_s: dict[str, float] = {}
    for step in steps:
        if step.status == "waiting" or step.effects == "human":
            continue  # waited for a person, an event or a timer: not counted (c-561, review 6)
        began, ended = _when(step.started_at), _when(step.finished_at) if step.finished_at else now
        if began is None or ended is None:
            continue
        ran_s[step.run_id] = ran_s.get(step.run_id, 0.0) + max(0.0, (ended - began).total_seconds())

    for a in active:
        if a.outcome is not None:
            # Its graph ended: it is waiting for the runs it started, never Stuck. One marked Stuck by mistake, or
            # one whose last run ended without settling it, is given the status its runs leave it.
            if a.status == "stuck" or a.id not in unfinished_children:
                found.append(Finding(a.tenant_id, a.id, "ended", "its graph ended; the runs it started decide"))
            continue
        rows = rows_of.get(a.id, [])
        quiet = _age_s(a.updated_at, now) >= quiet_s
        if rows and all(x.build != build for x in rows):
            found.append(Finding(a.tenant_id, a.id, "stuck", OLD_BUILD, set_aside=True))
            continue
        worst = max((int(x.lapses or 0) for x in rows), default=0)
        if worst > max_lapses and not any(_alive(x, now_s) for x in rows):
            died = max(_deaths(x, now_s) for x in rows)
            running, after = await _where(tx, a)
            found.append(Finding(a.tenant_id, a.id, "stuck", lapsed(died, running, after), set_aside=True))
            continue
        if a.id in child_ids and a.status in ("queued", "running"):
            parent_id = str(a.created_by)[len(CHILD_PREFIX) :]
            parent = parent_rows.get(parent_id)
            waits = cast(dict[str, Any], (parent.waiting if parent is not None else None) or {})
            payload = cast(dict[str, Any], waits.get("payload") or {})
            # A step with its own timeoutHours times out by the parent's timer already, by wall clock.
            own_limit = payload.get("kind") != "children" or payload.get("timeoutHours")
            if not own_limit and ran_s.get(a.id, 0.0) > child_limit_s:
                node = str(payload.get("node") or waits.get("node") or "")
                iteration = int(payload.get("iteration") or waits.get("iteration") or 1)
                where = {"run_id": parent_id, "node": node, "iteration": iteration}
                found.append(Finding(a.tenant_id, a.id, "child", TOO_LONG, parent=where))
                continue
        if rows or not quiet:
            continue
        if a.status in ("queued", "running"):
            found.append(Finding(a.tenant_id, a.id, "stuck", NOTHING_BEHIND))
            continue
        payload = cast(dict[str, Any], cast(dict[str, Any], a.waiting or {}).get("payload") or {})
        kind = payload.get("kind")
        if kind == "review":
            continue  # a person decides it: Human Tasks lists it
        if kind == "children" and a.id in unfinished_children:
            continue  # a child still running wakes it when it ends
        found.append(Finding(a.tenant_id, a.id, "stuck", NOTHING_LIVE))
    return found


async def settle(tx: Transactions, finding: Finding) -> bool:
    """Gives one finding its state, inside the finding's tenant (the caller enters it). False when the run moved on
    since it was read: a run already finished, cancelled or claimed is left as it is."""
    runs, w = RunStore(tx), engine_work
    run = await runs.get(finding.run_id)
    if finding.action == "ended":
        return run is not None and await runs.settle_ended(finding.run_id)
    if run is None or run["status"] not in ("queued", "running", "waiting"):
        return False
    if finding.action == "child":
        at = now_iso()
        await runs.update(finding.run_id, status="failed", error=f"It {finding.reason}.", finished_at=at)
        async with tx.tenant_tx() as c:
            await c.execute(
                w.update()
                .where(w.c.run_id == finding.run_id, w.c.status.in_(("queued", "claimed")))
                .values(status="failed", error=finding.reason, lease_expires_at=None)
            )
        parent = finding.parent
        # The same row the step's own timer would queue: its timeout port, with the rest of the children named.
        await WorkQueue(tx, owner="reconciler", ttl=0).enqueue(
            str(parent["run_id"]),
            "timeout",
            f"timeout:{parent['run_id']}:{parent['node']}:{parent['iteration']}",
            {"resume": {"timeout": True}, "node": parent["node"], "iteration": parent["iteration"]},
        )
        return True
    await runs.update(finding.run_id, status="stuck", error=finding.reason)
    if finding.set_aside:
        async with tx.tenant_tx() as c:
            await c.execute(
                w.update()
                .where(w.c.run_id == finding.run_id, w.c.status.in_(("queued", "claimed")))
                .values(status="stuck", lease_expires_at=None)
            )
    return True
