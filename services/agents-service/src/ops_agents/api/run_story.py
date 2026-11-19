"""A run told from its steps' output shapes: the email it began with, what each read step read, and each run its
steps started, with what that run was about, where it is now in words, its case and its Human Task.

Nothing here knows a workflow, a node id, a document type or a field name. Each part is recognised by the node type its
step runs (ops_engine shapes.py declares what each executor writes): the Email received trigger's input
(`shapes.EMAIL`), an Extract from file step's read, a Start workflow step's `runs` (or `children` with Wait for them).
The run page draws these as they come; it derives nothing."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, NotRequired, TypedDict, cast

from ops_agent_kernel.pii import masked
from ops_engine import default_registry
from ops_engine.compiler import redacted
from ops_engine.store import DefinitionRow, RunRow, RunStep, RunStore
from ops_engine.store.definitions import DefinitionStore
from ops_service_kit.http import Json, JsonList, JsonValue
from ops_service_kit.narrow import a_list, an_object, json_list, json_object

from ..store.actor_names import UNNAMED_WORKFLOW
from ..store.cases import CaseStore, CaseSummary
from ..store.engine import EngineTransactions
from ..store.review_assignments import ReviewAssignments
from . import engine_reviews
from .actors import NamedActors, actors, started_by_of
from .deps import Runtime
from .engine_runs import starters_of
from .file_names import named
from .review_text import describe_calls, humanize, operations

EMAIL_TRIGGER = "ops.trigger.email"
END = "ops.flow.end"
READ = "ai.extract"
START = "workflow.start"
REVIEW = "review.open"
# Ports an Extract from file step leaves by with a read in its output; `unreadable` and `error` carry none.
READ_PORTS = ("ok", "review")
# Runs told per Start workflow step, as many as the step starts by default; the rest are counted, not told.
MAX_CHILDREN = 50
# An id as a value (`fil_0f3a9c21`, `wfrun_edc46ea9518e`): links, never words.
_ID = re.compile(r"^[a-z]+_[A-Za-z0-9]{8,}$")
# Keys whose values are ids or enum words, left as they are when the story is masked.
_KEEP = frozenset(
    {"runId", "nodeId", "fileId", "caseId", "reviewId", "status", "outcome", "index", "open", "href", "at", "source"}
)


class FileRef(TypedDict):
    """A file id in a run's input with the name an upload gave beside it (`files_in`)."""

    id: str
    name: str | None


class Decision(TypedDict):
    """A decided Human Task step (`decisions_in`), keys in reply order; `by` is raw until the caller names it."""

    nodeId: JsonValue
    iteration: JsonValue
    reviewId: str
    action: str
    reason: str | None
    by: str | None
    at: str | None


class EmailAttachment(TypedDict):
    fileId: str
    name: str
    type: JsonValue
    size: JsonValue


class EmailSkipped(TypedDict):
    name: str
    message: str


class EmailBodyFile(TypedDict):
    fileId: str
    name: str


# The email a run began with (`email_of`), keys in reply order; `from` is a keyword, so the call form names it.
EmailView = TypedDict(
    "EmailView",
    {
        "from": str,
        "subject": str,
        "receivedAt": JsonValue,
        "body": str,
        "mailbox": JsonValue,
        "attachments": list[EmailAttachment],
        "skipped": list[EmailSkipped],
        "bodyFile": EmailBodyFile | None,
    },
)


class StartedEntry(TypedDict):
    """A run a Start workflow step started (`started_entries`)."""

    nodeId: str
    index: int
    runId: str
    label: JsonValue


class Fact(TypedDict):
    label: str
    value: str


class ChildCase(TypedDict):
    caseId: str
    subject: str
    customer: str | None
    facts: list[Fact]


class ChildTask(TypedDict):
    reviewId: str
    title: str
    open: bool
    decision: str | None
    state: str


class ChildHead(TypedDict):
    """A started run's own keys, first in its row (`children_view`)."""

    runId: str
    nodeId: str
    index: int
    workflowName: str
    stepName: str
    label: str
    status: str
    outcome: str | None


class ChildRow(ChildHead):
    """A run this run's steps started, as people read it: its own keys, then what it is told by, in reply order."""

    ending: str | None
    cases: list[ChildCase]
    tasks: list[ChildTask]
    state: str


class ReadEntry(TypedDict):
    """An Extract from file step that read something (`reads_of`)."""

    nodeId: str
    name: str
    read: engine_reviews.ReadView


class StoryView(TypedDict):
    """A run told for people (`story_view`), keys in reply order. The run page lifts `workflowName` out."""

    workflowName: NotRequired[str]
    email: EmailView | None
    reads: list[ReadEntry]
    children: list[ChildRow]
    childrenMore: int
    lines: list[Json]


def steps_view(rows: list[RunStep]) -> list[Json]:
    """Attempts grouped per node and iteration, in the order the steps started; each step shows its last attempt."""
    grouped: dict[tuple[str, int], list[RunStep]] = {}
    for r in rows:
        grouped.setdefault((r.node_id, r.iteration), []).append(r)
    out: list[Json] = []
    for (node, iteration), attempts in grouped.items():
        attempts.sort(key=lambda a: a.attempt)
        last = attempts[-1]
        out.append(
            {
                "nodeId": node,
                "iteration": iteration,
                "status": last.status,
                "port": last.port,
                "input": redacted(last.input),
                "output": redacted(last.output),
                "error": last.error,
                "attempts": [
                    {
                        "attempt": a.attempt,
                        "status": a.status,
                        "effects": a.effects,
                        "key": a.key,
                        "port": a.port,
                        "input": redacted(a.input),
                        "output": redacted(a.output),
                        "error": a.error,
                        "startedAt": a.started_at,
                        "finishedAt": a.finished_at,
                    }
                    for a in attempts
                ],
            }
        )
    return out


def decisions_in(run_id: str, steps: list[Json]) -> list[Decision]:
    """The decided Human Task steps: a step whose output carries the person's `decision`, with when its last attempt
    finished; `by` stays raw for the caller to name."""
    out: list[Decision] = []
    for s in steps:
        d = s.get("output")
        if s.get("status") != "ok" or not isinstance(d, dict):
            continue
        decision = d.get("decision")
        if not isinstance(decision, str):
            continue
        attempts = a_list(s.get("attempts") or [], "a step's attempts")
        finished: object = an_object(attempts[-1], "a step's attempt").get("finishedAt") if attempts else None
        out.append(
            {
                "nodeId": s["nodeId"],
                "iteration": s["iteration"],
                "reviewId": f"{run_id}:{s['nodeId']}:{s['iteration']}",
                "action": decision,
                "reason": reason if isinstance(reason := d.get("reason"), str) else None,
                "by": str(d["by"]) if d.get("by") else None,
                "at": finished.isoformat() if isinstance(finished, datetime) else (str(finished) if finished else None),
            }
        )
    return out


FILE_ID = re.compile(r"fil_[0-9a-f]{32}")


def files_in(value: JsonValue) -> list[FileRef]:
    """Every value in the input that is a file id, at any depth, once each and in order, with the name an upload gave
    beside it (`{fileId, name}`)."""
    found: dict[str, str | None] = {}

    def walk(v: JsonValue, name: str | None = None) -> None:
        if isinstance(v, str):
            if FILE_ID.fullmatch(v):
                found[v] = found.get(v) or name
        elif isinstance(v, dict):
            named = given if isinstance(given := v.get("name"), str) else None
            for k, x in v.items():
                walk(x, named if k == "fileId" else None)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(value)
    return [FileRef(id=i, name=n) for i, n in found.items()]


def nodes_of(stored: DefinitionRow | None) -> dict[str, Json]:
    return nodes_in(stored.definition if stored else None)


def nodes_in(definition: JsonValue) -> dict[str, Json]:
    """A stored definition's nodes by id; a definition with no node list has none."""
    listed = [json_object(n) for n in json_list(json_object(definition).get("nodes")) if isinstance(n, dict)]
    return {str(n["id"]): n for n in listed}


def executor_of(node: Json | None) -> str | None:
    if node is None:
        return None
    t = default_registry().find(str(node.get("type")), int(cast(int, node.get("typeVersion") or 1)))
    return t.executor if t is not None else None


def _name(node: Json | None, fallback: str) -> str:
    return str((node or {}).get("name") or fallback)


def workflow_name(stored: DefinitionRow | None) -> str:
    """A pinned version's name as people read it; a version with none is "a workflow run", never its id."""
    return (stored.name if stored else "").strip() or UNNAMED_WORKFLOW


def words(value: str) -> str:
    """An engine word ("not_ours") as a person reads it ("Not ours")."""
    text = re.sub(r"[_-]+", " ", value).strip()
    return text[:1].upper() + text[1:]


async def outcome_reads(rt: Runtime, rows: list[Json]) -> tuple[dict[str, str], dict[tuple[str, int], DefinitionRow]]:
    """The reads of `outcome_texts`: the End step of each run that ended and the versions they belong to."""
    ended = [r for r in rows if r.get("outcome") and r.get("status") in ("succeeded", "failed")]
    ends = await RunStore(EngineTransactions(rt.db)).ends([str(r["id"]) for r in ended])
    versions = await DefinitionStore(EngineTransactions(rt.db)).pinned(
        {(str(r["workflow_id"]), int(cast(int, r["version"]))) for r in ended if str(r["id"]) in ends}
    )
    return ends, versions


async def outcome_texts(rt: Runtime, rows: list[Json]) -> dict[str, str]:
    """How each run ended, as a sentence, by run id. The outcome itself is the End's key (`not_found`), which read
    bare looks like an error; the sentence names the End the run reached by its name in the workflow ("Finished at
    the Not found end."). A cancelled run's outcome is the reason given, kept as written. Two reads for a whole page:
    the End steps and the versions they belong to."""
    ends, versions = await outcome_reads(rt, rows)
    return outcome_sentences(rows, ends, versions)


def outcome_sentences(
    rows: list[Json], ends: dict[str, str], versions: dict[tuple[str, int], DefinitionRow]
) -> dict[str, str]:
    """`outcome_texts` from its reads."""
    out: dict[str, str] = {}
    for r in rows:
        if not r.get("outcome"):
            continue
        if r.get("status") not in ("succeeded", "failed"):
            out[str(r["id"])] = (
                "Cancelled by the person who started it" if r["outcome"] == "by_user" else str(r["outcome"])
            )
            continue
        stored = versions.get((str(r["workflow_id"]), int(cast(int, r["version"]))))
        nodes = [json_object(n) for n in json_list(json_object(stored.definition if stored else None).get("nodes"))]
        end = ends.get(str(r["id"]))
        name = next((str(n.get("name")) for n in nodes if n.get("id") == end and n.get("name")), None)
        said = name or words(str(r["outcome"]))
        verb = "Failed" if r["status"] == "failed" else "Finished"
        out[str(r["id"])] = f"{verb} at the {said} end."
    return out


def first_text(value: JsonValue) -> str | None:
    """The first text in a value that is not an id, depth first in its own order."""
    if isinstance(value, str):
        return value.strip() or None if not _ID.match(value) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None
    if isinstance(value, dict):
        for v in value.values():
            if (found := first_text(v)) is not None:
                return found
    if isinstance(value, list):
        found_all = [t for v in value if (t := first_text(v)) is not None]
        return ", ".join(found_all) or None
    return None


def email_of(run: Json, nodes: dict[str, Json]) -> EmailView | None:
    """The email a run began with, when its trigger is Email received; None for every other run."""
    given = run.get("input")
    if not any(n.get("type") == EMAIL_TRIGGER for n in nodes.values()) or not isinstance(given, dict):
        return None
    attachments = [a for a in cast(list[JsonValue], given.get("attachments") or []) if isinstance(a, dict)]
    skipped = [a for a in cast(list[JsonValue], given.get("skipped") or []) if isinstance(a, dict)]
    body = b if isinstance(b := given.get("bodyFile"), dict) else None
    return {
        "from": str(given.get("from") or ""),
        "subject": str(given.get("subject") or ""),
        "receivedAt": given.get("receivedAt"),
        "body": str(given.get("body") or ""),
        "mailbox": given.get("mailbox"),
        "attachments": [
            {
                "fileId": str(a.get("fileId")),
                "name": str(a.get("name") or a.get("fileId")),
                "type": a.get("mime"),
                "size": a.get("size"),
            }
            for a in attachments
            if a.get("fileId")
        ],
        "skipped": [{"name": str(a.get("name") or ""), "message": str(a.get("message") or "")} for a in skipped],
        "bodyFile": {"fileId": str(body["fileId"]), "name": str(body.get("name") or "")}
        if body and body.get("fileId")
        else None,
    }


def read_files(steps: list[Json], nodes: dict[str, Json], run_input: JsonValue = None) -> tuple[list[Json], list[Json]]:
    """Each Extract from file step that read something, and the files they read as `named` takes them: the name a file
    arrived with, as the run's input gives it, which files-service (one file per bytes, so its name is the first
    upload's) only fills in when the input does not name it."""
    found = [
        s
        for s in steps
        if executor_of(nodes.get(str(s["nodeId"]))) == READ
        and s.get("status") == "ok"
        and s.get("port") in READ_PORTS
        and engine_reviews.is_read(s.get("output"))
    ]
    given = {f["id"]: f["name"] for f in files_in(run_input)}
    wanted = [str(an_object(s["output"], "a read step's output")["fileId"]) for s in found]
    return found, [{"id": i, "name": given.get(i)} for i in wanted]


async def reads_of(
    rt: Runtime, team: str, steps: list[Json], nodes: dict[str, Json], run_input: JsonValue = None
) -> list[ReadEntry]:
    """Each Extract from file step that read something, as the read check draws it, the file named by files-service."""
    found, wanted = read_files(steps, nodes, run_input)
    files = await named(rt, team, wanted)
    return [
        {
            "nodeId": str(s["nodeId"]),
            "name": _name(nodes.get(str(s["nodeId"])), str(s["nodeId"])),
            "read": engine_reviews.read_view(an_object(s["output"], "a read step's output"), f.get("name"), None),
        }
        for s, f in zip(found, files, strict=True)
    ]


def started_entries(steps: list[Json], nodes: dict[str, Json]) -> tuple[list[StartedEntry], int]:
    """The runs the Start workflow steps started, each `{nodeId, index, runId, label}`, the first MAX_CHILDREN per step;
    and how many more there were."""
    out: list[StartedEntry] = []
    more = 0
    for s in steps:
        given = s.get("output")
        if executor_of(nodes.get(str(s["nodeId"]))) != START or not isinstance(given, dict):
            continue
        raw = cast(list[JsonValue], given.get("runs") or given.get("children") or [])
        listed = [r for r in raw if isinstance(r, dict) and r.get("runId")]
        more += max(0, len(listed) - MAX_CHILDREN)
        out += [
            StartedEntry(
                nodeId=str(s["nodeId"]),
                index=int(cast(int, r.get("index", i))),
                runId=str(r["runId"]),
                label=r.get("label"),
            )
            for i, r in enumerate(listed[:MAX_CHILDREN])
        ]
    return out, more


def _ending(steps: list[Json], nodes: dict[str, Json]) -> tuple[str | None, str | None]:
    """The End step a run finished on and the last step it ran, by name."""
    ends = [s for s in steps if nodes.get(str(s["nodeId"]), {}).get("type") == END and s.get("status") == "ok"]
    end = _name(nodes.get(str(ends[-1]["nodeId"])), str(ends[-1]["nodeId"])) if ends else None
    failed = [s for s in steps if s.get("status") not in ("ok", "running")]
    last = failed[-1] if failed else (steps[-1] if steps else None)
    return end, _name(nodes.get(str(last["nodeId"])), str(last["nodeId"])) if last else None


def _option_label(node: Json | None, decision: str) -> str:
    params = an_object((node or {}).get("parameters") or {}, "a step's parameters")
    for o in cast(list[JsonValue], params.get("options") or []):
        if isinstance(o, dict) and o.get("name") == decision:
            return str(o.get("label") or words(decision))
    return words(decision)


def decision_label(node: Json | None, decision: str) -> str:
    """A decision as a person reads it: Approved or Rejected, or the chosen option's label."""
    return {"approve": "Approved", "reject": "Rejected"}.get(decision) or _option_label(node, decision)


def state_of(child: Json, ending: str | None, last: str | None, open_task: bool) -> str:
    """Where a run is now, in words: the End step's name once it finished, or what it waits for."""
    status = str(child["status"])
    if status == "succeeded":
        return ending or words(str(child.get("outcome") or "finished"))
    if status == "failed":
        return f"Failed at {last}" if last else "Failed"
    if status == "cancelled":
        return "Cancelled"
    if status == "stuck":
        # Nothing is behind it: the run page says why and offers Retry and Cancel.
        return "Stuck"
    if open_task:
        return "Waiting for a person"
    if status == "waiting":
        return "Waiting on the runs it started"
    return "Not started yet" if status == "queued" else "Running"


def _facts(fields: Json) -> list[Fact]:
    """A case's own fields as labelled text: a list reads as each item's first text that is not an id."""
    out: list[Fact] = []
    for key, value in fields.items():
        text = first_text(value) if isinstance(value, (dict, list)) else (None if value is None else str(value))
        if text:
            out.append({"label": words(re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key)).capitalize(), "value": text})
    return out


@dataclass(frozen=True)
class ChildReads:
    """What the runs a run started are told from, read in one pass: `children_view` words them once `people` is
    asked."""

    started: list[StartedEntry]
    more: int
    found: dict[str, RunRow]
    steps_by_run: dict[str, list[Json]]
    pinned: dict[tuple[str, int], DefinitionRow]
    on_case: dict[str, str]
    summaries: dict[str, CaseSummary]
    assigned: dict[str, str]
    decided: dict[str, list[Decision]]
    own_nodes: dict[str, Json]

    def raws(self) -> list[str]:
        """Who the rows name, raw, for one actors() call: each person who decided a step and each assignee."""
        return [*(d["by"] for ds in self.decided.values() for d in ds if d["by"]), *self.assigned.values()]


async def children_reads(rt: Runtime, run: Json, steps: list[Json], nodes: dict[str, Json]) -> ChildReads:
    """The runs this run's steps started and everything their rows are told from. Every read is one query for all of
    them: their runs, steps, pinned definitions, cases and who their open tasks wait for."""
    started, more = started_entries(steps, nodes)
    store = RunStore(EngineTransactions(rt.db))
    found = {r.id: r for r in await store.many([c["runId"] for c in started])}
    # A run of another team is never told, whatever started it.
    started = [c for c in started if c["runId"] in found and found[c["runId"]].team_id == run["team_id"]]
    ids = [c["runId"] for c in started]
    steps_by_run = {rid: steps_view(rows) for rid, rows in (await store.steps_of(ids)).items()}
    pinned = await DefinitionStore(EngineTransactions(rt.db)).pinned(
        {(found[i].workflow_id, found[i].version) for i in ids}
    )
    cases = CaseStore(rt.db)
    on_case = await cases.cases_of_runs(ids)
    summaries = await cases.summaries(list(dict.fromkeys(on_case.values())), [str(run["team_id"])])
    open_reviews = [f"{rid}:{w['node']}:{w.get('iteration', 0)}" for rid in ids if (w := found[rid].waiting)]
    assigned = await ReviewAssignments(rt.db).current(open_reviews)
    decided = {rid: decisions_in(rid, steps_by_run.get(rid, [])) for rid in ids}
    own_nodes = nodes_in({"nodes": list[JsonValue](nodes.values())})
    return ChildReads(started, more, found, steps_by_run, pinned, on_case, summaries, assigned, decided, own_nodes)


def children_view(reads: ChildReads, people: NamedActors, *, scope: Any) -> tuple[list[ChildRow], int]:
    """The runs this run's steps started, as rows a person reads, and how many more there were."""
    started, found, pinned, own_nodes = reads.started, reads.found, reads.pinned, reads.own_nodes
    steps_by_run, decided, assigned = reads.steps_by_run, reads.decided, reads.assigned
    on_case, summaries, more = reads.on_case, reads.summaries, reads.more
    rows: list[ChildRow] = []
    for c in started:
        child = found[c["runId"]]
        stored = pinned.get((child.workflow_id, child.version))
        child_nodes = nodes_of(stored)
        child_steps = steps_by_run.get(c["runId"], [])
        workflow = workflow_name(stored)
        row: ChildHead = {
            "runId": c["runId"],
            "nodeId": c["nodeId"],
            "index": c["index"],
            "workflowName": workflow,
            "stepName": _name(own_nodes.get(c["nodeId"]), c["nodeId"]),
            "label": str(c["label"] or workflow),
            "status": child.status,
            "outcome": child.outcome,
        }
        # state_of reads a run's status and outcome only.
        said: Json = {"status": child.status, "outcome": child.outcome}
        if scope is not None and scope != ("workflow", child.workflow_id):
            # A key scoped to one workflow reads another workflow's runs by status alone.
            rows.append(
                {
                    **row,
                    "label": workflow,
                    "ending": None,
                    "cases": [],
                    "tasks": [],
                    "state": state_of(said, None, None, False),
                }
            )
            continue
        tasks: list[ChildTask] = []
        for d in decided[c["runId"]]:
            node = child_nodes.get(str(d["nodeId"]))
            title = _name(node, str(d["nodeId"]))
            label = _option_label(node, d["action"])
            by = people.get(d["by"] or "", {}).get("name") or d["by"]
            tasks.append(
                {
                    "reviewId": d["reviewId"],
                    "title": title,
                    "open": False,
                    "decision": label,
                    "state": f"{title}: {label}" + (f" by {by}" if by else ""),
                }
            )
        waiting = child.waiting
        open_task = bool(waiting) and executor_of(child_nodes.get(str((waiting or {}).get("node")))) == REVIEW
        if waiting and open_task:
            node = child_nodes.get(str(waiting["node"]))
            payload = an_object(waiting.get("payload") or {}, "a waiting step's payload")
            title = str(payload.get("title") or _name(node, str(waiting["node"])))
            review_id = f"{c['runId']}:{waiting['node']}:{waiting.get('iteration', 0)}"
            who = assigned.get(review_id)
            for_whom = (people.get(who, {}).get("name") or who) if who else "the team"
            tasks.append(
                {
                    "reviewId": review_id,
                    "title": title,
                    "open": True,
                    "decision": None,
                    # The step's name says what the person does ("Hold or flag"); the title is what Human Tasks lists.
                    "state": f"{_name(node, title)} · waiting for {for_whom}",
                }
            )
        ending, last = _ending(child_steps, child_nodes)
        case_id = on_case.get(c["runId"])
        summary = summaries.get(case_id) if case_id else None
        told: ChildRow = {
            **row,
            "ending": ending if child.status == "succeeded" else None,
            "state": state_of(said, ending, last, open_task),
            "cases": [
                {
                    "caseId": case_id,
                    "subject": summary.subject,
                    "customer": summary.customer,
                    "facts": _facts(summary.fields),
                }
            ]
            if case_id and summary
            else [],
            "tasks": tasks,
        }
        rows.append(told)
    return rows, more


def masked_story[T](value: T, key: str | None = None) -> T:
    """The story as people read it with masking on: every text but ids and enum words masked. The shape is kept: the
    same keys and lists, each text masked in place."""
    if key in _KEEP:
        return value
    if isinstance(value, dict):
        return cast(T, {k: masked_story(v, k) for k, v in cast(Json, value).items()})
    if isinstance(value, list):
        return cast(T, [masked_story(v) for v in cast(JsonList, value)])
    return cast(T, masked(value)) if isinstance(value, str) else value


# Where an email came from and arrived (`shapes.EMAIL`): channel metadata, shown with masking on. What the email and
# its documents say (subject, body, every value read) is content, masked like any other run data.
CHANNEL_FIELDS: tuple[Literal["from"], Literal["mailbox"]] = ("from", "mailbox")


async def channel_addresses(rt: Runtime, run: Json) -> set[str]:
    """The sender and mailbox of the email that started this run or, for a run another run started, its family's."""
    store, defs = RunStore(EngineTransactions(rt.db)), DefinitionStore(EngineTransactions(rt.db))
    team = cast(str | None, run.get("team_id"))
    above: list[Json] = [r.model_dump() for r in await starters_of(store, str(run.get("created_by") or ""), team)]
    for here in [run, *above]:
        version = cast(int | None, here.get("version"))
        email = email_of(here, nodes_of(await defs.row(str(here["workflow_id"]), version)))
        if email is not None:
            return {str(email[k]) for k in CHANNEL_FIELDS if email.get(k)}
    return set()


def keep_channel[T](shown: T, real: object, addresses: set[str]) -> T:
    """`shown` (masked) with every value that is one of `addresses` put back as it really reads. The shape is kept: a
    value put back is the text it masked."""
    if not addresses:
        return shown
    if isinstance(real, str):
        return cast(T, real) if real in addresses else shown
    if isinstance(real, dict) and isinstance(shown, dict):
        r, s = cast(Json, real), cast(Json, shown)
        return cast(T, {k: keep_channel(v, r.get(k), addresses) if k in r else v for k, v in s.items()})
    if isinstance(real, list) and isinstance(shown, list):
        r_list, s_list = cast(JsonList, real), cast(JsonList, shown)
        if len(r_list) == len(s_list):
            return cast(T, [keep_channel(v, x, addresses) for v, x in zip(s_list, r_list, strict=True)])
    return cast(T, shown)


TOOL = "gateway.call"
AI_STEPS = ("kernel.turn", "ai.prompt")
CASE_OPEN, CASE_ADD = "case.open", "case.add"
# The platform's reply operations (tools-service PLATFORM_TOOLS): a call to either is an email the run sent.
REPLY_TOOL, ACK_TOOL = "send_reply", "send_acknowledgement"
DECIDED = {"approve": "approved", "reject": "rejected"}


def _attempt_at(step: Json, key: str) -> str | None:
    attempts = a_list(step.get("attempts") or [], "a step's attempts")
    at: object = an_object(attempts[-1], "a step's attempt").get(key) if attempts else None
    return at.isoformat() if isinstance(at, datetime) else (str(at) if at else None)


def _line(at: JsonValue, source: str, actor: str, text: str, href: str | None) -> Json:
    return {"at": str(at) if at else None, "source": source, "actor": actor, "text": text, "href": href}


def tool_calls(steps: list[Json], nodes: dict[str, Json]) -> dict[str, Json]:
    """Each tool step's call, keyed `<nodeId>:<iteration>`, for describe_calls to word once per page."""
    out: dict[str, Json] = {}
    for st in steps:
        g = st.get("input")
        if executor_of(nodes.get(str(st["nodeId"]))) == TOOL and isinstance(g, dict):
            out[f"{st['nodeId']}:{st['iteration']}"] = {
                "tool": str(g.get("operation") or ""),
                "input": g.get("input") or {},
            }
    return out


def actors_in(run: Json, steps: list[Json]) -> list[str]:
    """Who a run's lines name, raw, for one actors() call: who started it and each person who decided a step."""
    return [started_by_of(run), *(str(d["by"]) for d in decisions_in(str(run["id"]), steps) if d["by"])]


def _read_text(read: Json, names: dict[str, str]) -> str:
    records = a_list(read.get("records") or ([{"fields": read["fields"]}] if read.get("fields") else []), "records")
    fields = [
        an_object(f, "a read field")
        for r in records
        for f in an_object(an_object(r, "a read record").get("fields") or {}, "a record's fields").values()
    ]
    check = sum(1 for f in fields if f.get("needsReview"))
    name = names.get(str(read.get("fileId") or "")) or "the document"
    counted = f"{plural(len(records), 'record')}, {plural(len(fields), 'field')}"
    return f"Read {name}: {counted}" + (f", {check} to check" if check else "")


def _review_title(run: Json, step: Json, node: Json | None, fallback: str) -> str:
    """A Human Task step's title as it was asked: the resolved title the step journaled or the run waits on, else the
    node's own title when it holds no expression, else the step's name; never an unresolved `{$...}`."""
    given = json_object(step.get("input"))
    waiting = an_object(run.get("waiting") or {}, "a run's waiting step")
    at_step = waiting.get("node") == step.get("nodeId")
    payload = an_object(waiting.get("payload") or {}, "a waiting step's payload") if at_step else {}
    param = an_object((node or {}).get("parameters") or {}, "a step's parameters").get("title")
    for t in (given.get("title"), payload.get("title"), param):
        if isinstance(t, str) and t.strip() and "{" not in t:
            return t
    return fallback


def masked_keeping(text: str, keep: set[str]) -> str:
    """`text` masked as people read it with masking on, except the channel addresses in `keep` (where an email came
    from and arrived), which stay as the Email section shows them."""
    tokens: dict[str, str] = {}
    for i, address in enumerate(sorted((a for a in keep if a), key=len, reverse=True)):
        if address in text:
            token = f"KEPTCHANNEL{i}Z"
            text = text.replace(address, token)
            tokens[token] = address
    out = cast(str, masked(text))
    for token, address in tokens.items():
        out = out.replace(token, address)
    return out


def masked_lines(told: list[Json], keep: set[str]) -> list[Json]:
    """Story lines as people read them with masking on: text and actor masked, the channel addresses kept."""
    return [
        line | {"text": masked_keeping(str(line["text"]), keep), "actor": masked_keeping(str(line["actor"]), keep)}
        for line in told
    ]


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def lines(
    run: Json,
    steps: list[Json],
    nodes: dict[str, Json],
    *,
    workflow: str,
    team: str,
    calls: dict[str, Json],
    who: NamedActors,
    started: dict[str, str] | None = None,
    started_names: dict[str, str] | None = None,
) -> list[Json]:
    """What a run did, one plain sentence per line, oldest first: `{at, source, actor, text, href}`. Each step is
    worded by its node's executor, the recognition `story()` uses, never by a node id or a workflow's own words; tool
    calls by `calls` (describe_calls) and people by `who` (actors). `started` is the runs its steps started that the
    reader may see, by id, with the label they may read (children_of's rows); a run outside it is neither named nor
    counted. The one wording of a run's steps: every page that tells what a run did draws these lines."""
    run_id = str(run["id"])
    page = f"/workflows/runs/{run_id}"
    out: list[Json] = []
    starter = who.get(started_by_of(run)) or {}
    name = str(starter.get("name") or run.get("created_by") or "")
    email = email_of(run, nodes)
    if email is not None:
        out.append(
            _line(
                run.get("created_at"),
                "email",
                email["from"],
                f"Email from {email['from']}: {email['subject'] or '(no subject)'}",
                page,
            )
        )
    elif starter.get("kind") == "person":
        via = an_object(starter.get("via") or {}, "how a run was started")
        how = f" from its {via['name']}" if via.get("kind") == "start" else ""
        out.append(_line(run.get("created_at"), "person", name, f"{name} started {workflow}{how}", page))
    elif starter.get("kind") == "key":
        out.append(
            _line(run.get("created_at"), "automation", name, f"Started {workflow} through the API ({name})", page)
        )
    elif starter.get("kind") == "event":
        out.append(_line(run.get("created_at"), "automation", name, f"Started {workflow} when {name}", page))
    else:
        out.append(_line(run.get("created_at"), "automation", name, f"{name} started {workflow}", page))
    names = {str(f["id"]): str(f["name"]) for f in files_in(run.get("input")) if f["name"]}
    for st in steps:
        node = nodes.get(str(st["nodeId"]))
        executor, step_name = executor_of(node), _name(node, str(st["nodeId"]))
        began, finished = _attempt_at(st, "startedAt"), _attempt_at(st, "finishedAt")
        port, output = st.get("port"), st.get("output")
        failed = st.get("status") not in ("ok", "running", "waiting") or port == "error"
        o: Json = output if isinstance(output, dict) else {}
        key = f"{st['nodeId']}:{st['iteration']}"
        if executor == READ and port in READ_PORTS:
            href = f"/files?file={o['fileId']}" if o.get("fileId") else page
            out.append(_line(finished, "automation", workflow, _read_text(o, names), href))
        elif executor in AI_STEPS and not failed:
            said = first_text(output)
            if said:
                out.append(_line(finished, "automation", workflow, f"{step_name}: {said[:160]}", page))
        elif executor == TOOL:
            told = calls.get(key) or {}
            g = an_object(st.get("input") or {}, "a tool step's input")
            if g.get("operation") in (REPLY_TOOL, ACK_TOOL) and not failed:
                given = an_object(g.get("input") or {}, "a reply's input")
                out.append(
                    _line(
                        finished,
                        "email",
                        workflow,
                        f"Replied to {given.get('to') or 'the sender'}: {given.get('subject') or '(no subject)'}",
                        page,
                    )
                )
            else:
                said = str(told.get("sentence") or humanize(str(g.get("operation") or "")) or step_name)
                out.append(_line(finished or began, "automation", workflow, f"{said} failed" if failed else said, page))
        elif executor == REVIEW:
            title = _review_title(run, st, node, step_name)
            task = f"/reviews/{run_id}:{st['nodeId']}:{st['iteration']}"
            out.append(_line(began, "automation", workflow, f"Asked {team}: {title}", task))
            if isinstance(o.get("decision"), str):
                by = who.get(str(o.get("by") or "")) or {}
                person = str(by.get("name") or o.get("by") or "Someone")
                decision = str(o["decision"])
                verb = DECIDED.get(decision) or f"chose {_option_label(node, decision)}"
                out.append(_line(finished, "person", person, f"{person} {verb}: {title}", task))
        elif executor == CASE_OPEN and not failed:
            given = an_object(st.get("input") or {}, "an Open case step's input")
            href = f"/cases/{o['caseId']}" if o.get("caseId") else None
            out.append(
                _line(finished, "automation", workflow, f"Opened a case: {given.get('subject') or step_name}", href)
            )
        elif executor == CASE_ADD and not failed:
            given = an_object(st.get("input") or {}, "an Add to case step's input")
            # Each key of the fields set, as the step's input holds them.
            set_fields = cast(Iterable[JsonValue], given.get("fields") or {})
            added = ", ".join(humanize(str(k)).lower() for k in set_fields)
            out.append(_line(finished, "automation", workflow, f"Added {added or 'details'} to the case", page))
        elif executor == START and not failed:
            listed = a_list(o.get("runs") or o.get("children") or [], "the runs a step started")
            runs = [an_object(r, "a started run") for r in listed]
            if started is not None:
                runs = [r | {"label": started[str(r.get("runId"))]} for r in runs if str(r.get("runId")) in started]
            if runs:
                labels = ", ".join(str(r.get("label")) for r in runs[:5] if r.get("label"))
                more = f" and {len(runs) - 5} more" if len(runs) > 5 else ""
                # The started workflow by its name (`started_names`, run id to workflow name), never its id.
                named = [n for r in runs if (n := (started_names or {}).get(str(r.get("runId"))))]
                child = named[0] if named else humanize(str(o.get("workflowId") or step_name))
                out.append(
                    _line(
                        finished,
                        "automation",
                        workflow,
                        f"Started {plural(len(runs), 'run')} of {child}" + (f": {labels}{more}" if labels else ""),
                        page,
                    )
                )
        elif node is not None and node.get("type") == END and not failed:
            out.append(_line(finished, "automation", workflow, f"{workflow} finished: {step_name}", page))
    # How the run began comes first; its steps follow in the order they finished.
    return [out[0], *sorted(out[1:], key=lambda x: str(x["at"] or ""))]


@dataclass(frozen=True)
class StoryReads:
    """A run's story as the database holds it: the version it pinned, the runs it started and its email's addresses."""

    stored: DefinitionRow | None
    children: ChildReads
    addresses: set[str]

    def raws(self, run: Json, steps: list[Json]) -> list[str]:
        """Every actor the story names, raw, for the one actors() call that answers them all."""
        return [*actors_in(run, steps), *self.children.raws()]


async def story_reads(rt: Runtime, run: Json, steps: list[Json]) -> StoryReads:
    """The reads of `story`, all local: run it in the route's transaction, then ask outside with none open."""
    version = cast(int | None, run.get("version"))
    stored = await DefinitionStore(EngineTransactions(rt.db)).row(str(run["workflow_id"]), version)
    children = await children_reads(rt, run, steps, nodes_of(stored))
    return StoryReads(stored, children, await channel_addresses(rt, run))


async def ask_story(rt: Runtime, run: Json, steps: list[Json], reads: StoryReads) -> None:
    """Warms what `story` words the run with, so building it asks no other service: the file names and the tool
    directory (each kept for the request)."""
    nodes = nodes_of(reads.stored)
    await named(rt, str(run["team_id"]), read_files(steps, nodes, run.get("input"))[1])
    if tool_calls(steps, nodes):
        await operations(rt)


async def story_view(
    rt: Runtime,
    run: Json,
    steps: list[Json],
    reads: StoryReads,
    *,
    who: NamedActors,
    team_name: str,
    scope: Any,
    masking: bool,
) -> StoryView:
    """The run told for people: `email`, `reads` and `children` (with `childrenMore`), from the version it pinned.
    `who` names every actor `reads.raws` listed and `team_name` the run's team: both asked before this builds."""
    stored = reads.stored
    nodes = nodes_of(stored)
    children, more = children_view(reads.children, who, scope=scope)
    told: StoryView = {
        "workflowName": workflow_name(stored),
        "email": email_of(run, nodes),
        "reads": await reads_of(rt, str(run["team_id"]), steps, nodes, run.get("input")),
        "children": children,
        "childrenMore": more,
        "lines": lines(
            run,
            steps,
            nodes,
            workflow=workflow_name(stored),
            team=team_name,
            calls=await describe_calls(rt, tool_calls(steps, nodes)),
            who=who,
            started={str(c["runId"]): str(c["label"]) for c in children},
            started_names={str(c["runId"]): str(c["workflowName"]) for c in children},
        ),
    }
    return masked_story(told) if masking else told


async def story(rt: Runtime, run: Json, steps: list[Json], *, scope: Any, masking: bool) -> StoryView:
    """`story_view` after its reads and the names it asks for, for a caller that holds no transaction of its own."""
    reads = await story_reads(rt, run, steps)
    names = getattr(rt, "team_names", None)
    team = str(run["team_id"])
    team_name = (await names.name(team) if names is not None else None) or team
    who = await actors(rt, reads.raws(run, steps))
    return await story_view(rt, run, steps, reads, who=who, team_name=team_name, scope=scope, masking=masking)
