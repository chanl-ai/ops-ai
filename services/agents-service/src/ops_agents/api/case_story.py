"""A case told for people (c-500): how its work began and everything that happened to it. Everything is read in the
case's team only; a run of another team does not exist for the case page (identity-and-tenancy.md, "The team is the
workspace")."""

from __future__ import annotations

from typing import Any, cast

from ops_engine.store import CHILD_PREFIX, DefinitionStore, RunStore

from ..case_wording import entry
from ..store.cases import CaseStore
from ..store.engine import EngineTransactions
from .actors import actors, started_by_of
from .deps import Runtime
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


async def origin(rt: Runtime, row: dict[str, Any]) -> dict[str, Any]:
    """How the case's work began: the first run of the chain that opened it, worded from that run's trigger, or the
    person or key that opened it by hand."""
    by = str(row["created_by"] or "")
    if not by.startswith(CHILD_PREFIX):
        who = (await actors(rt, [by])).get(by) or {}
        return _origin("person", f"Opened by {who.get('name') or by}")
    tx = EngineTransactions(rt.db)
    runs = RunStore(tx)
    opener = await runs.get(by[len(CHILD_PREFIX) :])
    if opener is None or opener.get("team_id") != row["team_id"]:
        return _origin("other", "Opened by a workflow")
    first = await first_run(runs, opener)
    stored = await DefinitionStore(tx).get(str(first["workflow_id"]), first.get("version")) or {}
    nodes = nodes_of(stored)
    workflow = str(stored.get("name") or first["workflow_id"])
    trigger = next((str(n.get("type")) for n in nodes.values() if str(n.get("type")).startswith("ops.trigger.")), "")
    run_id = str(first["id"])
    if trigger == EMAIL and (email := email_of(first, nodes)) is not None:
        return _origin("email", f"From an email from {email['from']}: {email['subject'] or '(no subject)'}", run_id)
    starter = started_by_of(first)
    who = (await actors(rt, [starter])).get(starter) or {}
    name = str(who.get("name") or starter)
    if trigger == EVENT or who.get("kind") == "event":
        return _origin("event", f"Started {workflow} when {name}", run_id)
    if trigger == REQUEST and who.get("kind") == "key":
        return _origin("request", f"Started {workflow} through the API ({name})", run_id)
    if trigger == REQUEST and who.get("kind") == "person":
        via = cast(dict[str, Any], who.get("via") or {})
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


async def feed(
    rt: Runtime, row: dict[str, Any], runs: list[dict[str, Any]], *, scope: Any, masking: bool = False
) -> dict[str, Any]:
    """Everything that happened to the case, newest first: the lines of each run linked to it (run_story.lines, the
    run page's wording) and its own timeline in case_wording's. `runs` are the case's runs in its team
    (CaseLinks.runs); a key scoped to one workflow reads that workflow's runs only. A fixed number of reads whatever the
    number of runs: their steps, their versions, the tool directory, the runs they started, the case's events, and the
    names of everyone the lines mention."""
    team = str(row["team_id"])
    tx = EngineTransactions(rt.db)
    store = RunStore(tx)
    # The runs that led to the case's own run (an email intake above a read), in its team: their lines are how the
    # matter began, which no link records on the case.
    by = str(row["created_by"] or "")
    opener = await store.get(by[len(CHILD_PREFIX) :]) if by.startswith(CHILD_PREFIX) else None
    if opener is not None and opener.get("team_id") == team:
        linked = {str(r["id"]) for r in runs}
        runs = [*runs, *(r for r in await runs_above(store, opener) if str(r["id"]) not in linked)]
    if scope is not None and scope[0] == "workflow":
        runs = [r for r in runs if r["workflow_id"] == scope[1]]
    by_run = await store.steps_of([str(r["id"]) for r in runs])
    steps = {str(r["id"]): steps_view(by_run.get(str(r["id"]), [])) for r in runs}
    keys = {(str(r["workflow_id"]), int(r["version"])) for r in runs if r.get("version") is not None}
    pinned = await DefinitionStore(tx).pinned(keys)
    nodes = {str(r["id"]): nodes_of(pinned.get((str(r["workflow_id"]), int(r.get("version") or 0)))) for r in runs}
    calls = {f"{rid}|{k}": c for rid in steps for k, c in tool_calls(steps[rid], nodes[rid]).items()}
    described = await describe_calls(rt, calls)
    started = {rid: _started(steps[rid], nodes[rid]) for rid in steps}
    kids = [
        c for c in await store.many([cid for pairs in started.values() for cid, _ in pairs]) if c["team_id"] == team
    ]
    seen = {str(c["id"]) for c in kids}
    kid_keys = {(str(c["workflow_id"]), int(c["version"])) for c in kids if c.get("version") is not None}
    kid_versions = await DefinitionStore(tx).pinned(kid_keys)
    kid_names = {
        str(c["id"]): str(
            (kid_versions.get((str(c["workflow_id"]), int(c.get("version") or 0))) or {}).get("name")
            or c["workflow_id"]
        )
        for c in kids
    }
    events = await CaseStore(rt.db).events(str(row["id"]))
    raws = [a for r in runs for a in actors_in(r, steps[str(r["id"])])]
    raws += [str(e["by"]) for e in events] + [str(e["detail"].get("after")) for e in events if e["kind"] == "field"]
    who = await actors(rt, raws)
    names = getattr(rt, "team_names", None)
    team_name = (await names.name(team) if names is not None else None) or team
    told: list[dict[str, Any]] = []
    for r in runs:
        rid = str(r["id"])
        told += lines(
            r,
            steps[rid],
            nodes[rid],
            workflow=str(
                r.get("workflow_name")
                or (pinned.get((str(r["workflow_id"]), int(r.get("version") or 0))) or {}).get("name")
                or r["workflow_id"]
            ),
            team=team_name,
            calls={k.split("|", 1)[1]: v for k, v in described.items() if k.startswith(f"{rid}|")},
            who=who,
            started={cid: label for cid, label in started[rid] if cid in seen},
            started_names=kid_names,
        )
    people = {raw: str(v.get("name") or raw) for raw, v in who.items()}
    told_runs = {f"{CHILD_PREFIX}{r['id']}" for r in runs}
    for e in events:
        if e["kind"] == "opened" and str(e["by"]) in told_runs:
            continue  # the run's own "Opened a case" line says it
        actor = who.get(str(e["by"])) or {}
        name = str(actor.get("name") or e["by"])
        said = entry(str(e["kind"]), cast(dict[str, Any], e["detail"]), name, people)
        if said:
            source = "person" if actor.get("kind", "person") == "person" else "automation"
            href = f"/cases/{e['detail']['case']}" if e["kind"] == "link" and e["detail"].get("case") else None
            told.append({"at": e["at"], "source": source, "actor": name, "text": said, "href": href})
    told.sort(key=lambda x: x["at"] or "", reverse=True)
    if masking:
        # Where an email came from and arrived stays shown, as on the run page; everything else is masked.
        emails = [e for r in runs if (e := email_of(r, nodes[str(r["id"])])) is not None]
        told = masked_lines(told, {str(e[k]) for e in emails for k in CHANNEL_FIELDS if e.get(k)})
    return {"lines": told[:FEED_CAP], "more": max(0, len(told) - FEED_CAP)}
