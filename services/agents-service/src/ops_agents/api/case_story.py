"""A case told for people: how its work began and everything that happened to it. Everything is read in the
case's team only; a run of another team does not exist for the case page (identity-and-tenancy.md, "The team is the
workspace")."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from ops_engine.store import CHILD_PREFIX, DefinitionRow, DefinitionStore, RunStore

from ..case_wording import entry
from ..store.cases import CaseEventRecord, CaseRecord, CaseStore
from ..store.engine import EngineTransactions
from .actors import actors, started_by_of
from .deps import Runtime
from .engine_reviews import Row
from .engine_runs import first_run, runs_above
from .review_text import describe_calls
from .run_story import (
    CHANNEL_FIELDS,
    START,
    actors_in,
    email_of,
    executor_of,
    lines,
    masked_lines,
    nodes_of,
    steps_view,
    tool_calls,
)

EMAIL, REQUEST, EVENT = "ops.trigger.email", "ops.trigger.request", "ops.trigger.event"
# Lines a case's feed shows; past it the rest are counted.
FEED_CAP = 200


def _origin(kind: str, text: str, run_id: str | None = None) -> dict[str, Any]:
    return {"kind": kind, "text": text, "runId": run_id, "href": f"/workflows/runs/{run_id}" if run_id else None}


@dataclass(frozen=True)
class OriginReads:
    """How a case's work began, as far as the database tells: `told` when that needs no name, else who to ask for."""

    told: Row | None
    # A person who opened it by hand, or the run's starter, raw; `kind` says which wording applies.
    who: str
    kind: str
    workflow: str = ""
    trigger: str = ""
    run_id: str | None = None

    def raws(self) -> list[str]:
        return [] if self.told is not None else [self.who]


async def origin_reads(rt: Runtime, row: CaseRecord) -> OriginReads:
    """The reads of `origin`: the first run of the chain that opened the case, and its trigger."""
    by = str(row.created_by or "")
    if not by.startswith(CHILD_PREFIX):
        return OriginReads(None, by, "person")
    tx = EngineTransactions(rt.db)
    runs = RunStore(tx)
    opener = await runs.row(by[len(CHILD_PREFIX) :])
    if opener is None or opener.team_id != row.team_id:
        return OriginReads(_origin("other", "Opened by a workflow"), by, "other")
    first = await first_run(runs, opener)
    stored = await DefinitionStore(tx).row(first.workflow_id, first.version)
    nodes = nodes_of(stored)
    workflow = (stored.name if stored else "") or first.workflow_id
    trigger = next((str(n.get("type")) for n in nodes.values() if str(n.get("type")).startswith("ops.trigger.")), "")
    run_id = first.id
    if trigger == EMAIL and (email := email_of(first.model_dump(), nodes)) is not None:
        told = _origin("email", f"From an email from {email['from']}: {email['subject'] or '(no subject)'}", run_id)
        return OriginReads(told, by, "email")
    return OriginReads(None, started_by_of(first.model_dump()), "run", workflow, trigger, run_id)


async def origin(rt: Runtime, row: CaseRecord) -> Row:
    """`origin_view` after its reads, for a caller that asks for the names itself."""
    reads = await origin_reads(rt, row)
    return origin_view(reads, await actors(rt, reads.raws()))


def origin_view(reads: OriginReads, who: dict[str, Row]) -> Row:
    """How the case's work began: the first run of the chain that opened it, worded from that run's trigger, or the
    person or key that opened it by hand. `who` names `reads.raws()`."""
    if reads.told is not None:
        return reads.told
    named = who.get(reads.who) or {}
    if reads.kind == "person":
        return _origin("person", f"Opened by {named.get('name') or reads.who}")
    name = str(named.get("name") or reads.who)
    workflow, trigger, run_id = reads.workflow, reads.trigger, reads.run_id
    if trigger == EVENT or named.get("kind") == "event":
        return _origin("event", f"Started {workflow} when {name}", run_id)
    if trigger == REQUEST and named.get("kind") == "key":
        return _origin("request", f"Started {workflow} through the API ({name})", run_id)
    if trigger == REQUEST and named.get("kind") == "person":
        via = cast(Row, named.get("via") or {})
        how = f" from its {via['name']}" if via.get("kind") == "start" else ""
        return _origin("request", f"{name} started {workflow}{how}", run_id)
    return _origin("other", f"Started by {workflow}", run_id)


def _started(steps: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    """Each run a Start workflow step started: (run id, its label)."""
    out: list[tuple[str, str]] = []
    for st in steps:
        o = st.get("output")
        if executor_of(nodes.get(str(st["nodeId"]))) == START and isinstance(o, dict):
            given = cast(dict[str, Any], o)
            for r in cast(list[dict[str, Any]], given.get("runs") or given.get("children") or []):
                out.append((str(r.get("runId")), str(r.get("label") or "")))
    return out


@dataclass(frozen=True)
class FeedReads:
    """What a case's feed is told from, read in one pass: `feed_view` words it once `who` is asked."""

    runs: list[Row]
    steps: dict[str, list[Row]]
    pinned: dict[tuple[str, int], DefinitionRow]
    nodes: dict[str, dict[str, Row]]
    calls: dict[str, Row]
    started: dict[str, list[tuple[str, str]]]
    seen: set[str]
    kid_names: dict[str, str]
    events: list[CaseEventRecord]

    def raws(self) -> list[str]:
        """Everyone the lines and the case's own timeline mention, raw."""
        raws = [a for r in self.runs for a in actors_in(r, self.steps[str(r["id"])])]
        return (
            raws + [e.by for e in self.events] + [str(e.detail.get("after")) for e in self.events if e.kind == "field"]
        )


async def feed_reads(rt: Runtime, row: CaseRecord, runs: list[Row], *, scope: Any) -> FeedReads:
    """The reads of `feed`: a fixed number whatever the number of runs: their steps, their versions, the runs they
    started and the case's events. `runs` are the case's runs in its team (CaseLinks.runs); a key scoped to one workflow
    reads that workflow's runs only."""
    team = str(row.team_id)
    tx = EngineTransactions(rt.db)
    store = RunStore(tx)
    # The runs that led to the case's own run (an email intake above a read), in its team: their lines are how the
    # matter began, which no link records on the case.
    by = str(row.created_by or "")
    opener = await store.row(by[len(CHILD_PREFIX) :]) if by.startswith(CHILD_PREFIX) else None
    if opener is not None and opener.team_id == team:
        linked = {str(r["id"]) for r in runs}
        runs = [*runs, *(r.model_dump() for r in await runs_above(store, opener) if r.id not in linked)]
    if scope is not None and scope[0] == "workflow":
        runs = [r for r in runs if r["workflow_id"] == scope[1]]
    by_run = await store.steps_of([str(r["id"]) for r in runs])
    steps = {str(r["id"]): steps_view(by_run.get(str(r["id"]), [])) for r in runs}
    keys = {(str(r["workflow_id"]), int(r["version"])) for r in runs if r.get("version") is not None}
    pinned = await DefinitionStore(tx).pinned(keys)
    nodes = {str(r["id"]): nodes_of(pinned.get((str(r["workflow_id"]), int(r.get("version") or 0)))) for r in runs}
    calls = {f"{rid}|{k}": c for rid in steps for k, c in tool_calls(steps[rid], nodes[rid]).items()}
    started = {rid: _started(steps[rid], nodes[rid]) for rid in steps}
    kids = [c for c in await store.many([cid for pairs in started.values() for cid, _ in pairs]) if c.team_id == team]
    seen = {c.id for c in kids}
    kid_keys = {(c.workflow_id, c.version) for c in kids}
    kid_versions = await DefinitionStore(tx).pinned(kid_keys)
    kid_names = {
        c.id: (v.name if (v := kid_versions.get((c.workflow_id, c.version))) else "") or c.workflow_id for c in kids
    }
    events = await CaseStore(rt.db).events(str(row.id))
    return FeedReads(runs, steps, pinned, nodes, calls, started, seen, kid_names, events)


async def feed_view(
    rt: Runtime, reads: FeedReads, *, who: dict[str, Row], team_name: str, masking: bool = False
) -> Row:
    """Everything that happened to the case, newest first: the lines of each run linked to it (run_story.lines, the
    run page's wording) and its own timeline in case_wording's. `who` names `reads.raws()` and `team_name` the case's
    team; the tool directory is read once for every call the lines word."""
    runs, steps, nodes, pinned = reads.runs, reads.steps, reads.nodes, reads.pinned
    described = await describe_calls(rt, reads.calls)
    told: list[dict[str, Any]] = []
    for r in runs:
        rid = str(r["id"])
        told += lines(
            r,
            steps[rid],
            nodes[rid],
            workflow=str(
                r.get("workflow_name")
                or (v.name if (v := pinned.get((str(r["workflow_id"]), int(r.get("version") or 0)))) else None)
                or r["workflow_id"]
            ),
            team=team_name,
            calls={k.split("|", 1)[1]: v for k, v in described.items() if k.startswith(f"{rid}|")},
            who=who,
            started={cid: label for cid, label in reads.started[rid] if cid in reads.seen},
            started_names=reads.kid_names,
        )
    people = {raw: str(v.get("name") or raw) for raw, v in who.items()}
    told_runs = {f"{CHILD_PREFIX}{r['id']}" for r in runs}
    for e in reads.events:
        if e.kind == "opened" and e.by in told_runs:
            continue  # the run's own "Opened a case" line says it
        actor = who.get(e.by) or {}
        name = str(actor.get("name") or e.by)
        said = entry(e.kind, e.detail, name, people)
        if said:
            source = "person" if actor.get("kind", "person") == "person" else "automation"
            href = f"/cases/{e.detail['case']}" if e.kind == "link" and e.detail.get("case") else None
            told.append({"at": e.at, "source": source, "actor": name, "text": said, "href": href})
    told.sort(key=lambda x: x["at"] or "", reverse=True)
    if masking:
        # Where an email came from and arrived stays shown, as on the run page; everything else is masked.
        emails = [e for r in runs if (e := email_of(r, nodes[str(r["id"])])) is not None]
        told = masked_lines(told, {str(e[k]) for e in emails for k in CHANNEL_FIELDS if e.get(k)})
    return {"lines": told[:FEED_CAP], "more": max(0, len(told) - FEED_CAP)}


async def feed(rt: Runtime, row: CaseRecord, runs: list[Row], *, scope: Any, masking: bool = False) -> Row:
    """`feed_view` after its reads, for a caller that asks for the names itself."""
    reads = await feed_reads(rt, row, runs, scope=scope)
    names = getattr(rt, "team_names", None)
    team = str(row.team_id)
    team_name = (await names.name(team) if names is not None else None) or team
    return await feed_view(rt, reads, who=await actors(rt, reads.raws()), team_name=team_name, masking=masking)
