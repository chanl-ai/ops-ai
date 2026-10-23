"""A run told from its steps' output shapes (c-477): the email it began with, what each read step read, and each run its
steps started, with what that run was about, where it is now in words, its case and its Human Task.

Nothing here knows a workflow, a node id, a document type or a field name. Each part is recognised by the node type its
step runs (ops_engine shapes.py declares what each executor writes): the Email received trigger's input
(`shapes.EMAIL`), an Extract from file step's read, a Start workflow step's `runs` (or `children` with Wait for them).
The run page draws these as they come; it derives nothing."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, cast

from ops_agent_kernel.pii import masked
from ops_engine import default_registry
from ops_engine.compiler import redacted
from ops_engine.store import RunStore
from ops_engine.store.definitions import DefinitionStore

from ..store.actor_names import UNNAMED_WORKFLOW
from ..store.cases import CaseStore
from ..store.engine import EngineTransactions
from ..store.review_assignments import ReviewAssignments
from . import engine_reviews
from .actors import actors, started_by_of
from .deps import Runtime
from .engine_runs import runs_above
from .file_names import named
from .review_text import describe_calls, humanize

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


def steps_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attempts grouped per node and iteration, in the order the steps started; each step shows its last attempt."""
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault((r["node_id"], r["iteration"]), []).append(r)
    out: list[dict[str, Any]] = []
    for (node, iteration), attempts in grouped.items():
        attempts.sort(key=lambda a: a["attempt"])
        last = attempts[-1]
        out.append(
            {
                "nodeId": node,
                "iteration": iteration,
                "status": last["status"],
                "port": last["port"],
                "input": redacted(last["input"]),
                "output": redacted(last["output"]),
                "error": last["error"],
                "attempts": [
                    {
                        "attempt": a["attempt"],
                        "status": a["status"],
                        "effects": a["effects"],
                        "key": a["key"],
                        "port": a["port"],
                        "input": redacted(a["input"]),
                        "output": redacted(a["output"]),
                        "error": a["error"],
                        "startedAt": a["started_at"],
                        "finishedAt": a["finished_at"],
                    }
                    for a in attempts
                ],
            }
        )
    return out


def decisions_in(run_id: str, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The decided Human Task steps: a step whose output carries the person's `decision`, with when its last attempt
    finished; `by` stays raw for the caller to name."""
    out: list[dict[str, Any]] = []
    for s in steps:
        o = s.get("output")
        if s.get("status") != "ok" or not isinstance(o, dict):
            continue
        d = cast(dict[str, Any], o)
        if not isinstance(d.get("decision"), str):
            continue
        attempts = cast(list[dict[str, Any]], s.get("attempts") or [])
        finished = attempts[-1].get("finishedAt") if attempts else None
        out.append(
            {
                "nodeId": s["nodeId"],
                "iteration": s["iteration"],
                "reviewId": f"{run_id}:{s['nodeId']}:{s['iteration']}",
                "action": d["decision"],
                "reason": d.get("reason") if isinstance(d.get("reason"), str) else None,
                "by": str(d["by"]) if d.get("by") else None,
                "at": finished.isoformat() if isinstance(finished, datetime) else (str(finished) if finished else None),
            }
        )
    return out


FILE_ID = re.compile(r"fil_[0-9a-f]{32}")


def files_in(value: Any) -> list[dict[str, Any]]:
    """Every value in the input that is a file id, at any depth, once each and in order, with the name an upload gave
    beside it (`{fileId, name}`)."""
    found: dict[str, str | None] = {}

    def walk(v: Any, name: str | None = None) -> None:
        if isinstance(v, str):
            if FILE_ID.fullmatch(v):
                found[v] = found.get(v) or name
        elif isinstance(v, dict):
            d = cast(dict[str, Any], v)
            named = d.get("name") if isinstance(d.get("name"), str) else None
            for k, x in d.items():
                walk(x, named if k == "fileId" else None)
        elif isinstance(v, list):
            for x in cast(list[Any], v):
                walk(x)

    walk(value)
    return [{"id": i, "name": n} for i, n in found.items()]


def nodes_of(stored: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    definition = cast(dict[str, Any], (stored or {}).get("definition") or {})
    listed = [cast(dict[str, Any], n) for n in cast(list[Any], definition.get("nodes") or []) if isinstance(n, dict)]
    return {str(n["id"]): n for n in listed}


def executor_of(node: dict[str, Any] | None) -> str | None:
    if node is None:
        return None
    t = default_registry().find(str(node.get("type")), int(node.get("typeVersion") or 1))
    return t.executor if t is not None else None


def _name(node: dict[str, Any] | None, fallback: str) -> str:
    return str((node or {}).get("name") or fallback)


def workflow_name(stored: dict[str, Any] | None) -> str:
    """A pinned version's name as people read it; a version with none is "a workflow run", never its id."""
    return str((stored or {}).get("name") or "").strip() or UNNAMED_WORKFLOW


def words(value: str) -> str:
    """An engine word ("not_ours") as a person reads it ("Not ours")."""
    text = re.sub(r"[_-]+", " ", value).strip()
    return text[:1].upper() + text[1:]


def first_text(value: Any) -> str | None:
    """The first text in a value that is not an id, depth first in its own order."""
    if isinstance(value, str):
        return value.strip() or None if not _ID.match(value) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None
    if isinstance(value, dict):
        for v in cast(dict[str, Any], value).values():
            if (found := first_text(v)) is not None:
                return found
    if isinstance(value, list):
        found_all = [t for v in cast(list[Any], value) if (t := first_text(v)) is not None]
        return ", ".join(found_all) or None
    return None


def email_of(run: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """The email a run began with, when its trigger is Email received; None for every other run."""
    if not any(n.get("type") == EMAIL_TRIGGER for n in nodes.values()) or not isinstance(run.get("input"), dict):
        return None
    given = cast(dict[str, Any], run["input"])
    attachments = [
        cast(dict[str, Any], a) for a in cast(list[Any], given.get("attachments") or []) if isinstance(a, dict)
    ]
    skipped = [cast(dict[str, Any], a) for a in cast(list[Any], given.get("skipped") or []) if isinstance(a, dict)]
    body = cast(dict[str, Any], given.get("bodyFile")) if isinstance(given.get("bodyFile"), dict) else None
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


async def reads_of(
    rt: Runtime, team: str, steps: list[dict[str, Any]], nodes: dict[str, dict[str, Any]], run_input: Any = None
) -> list[dict[str, Any]]:
    """Each Extract from file step that read something, as the read check draws it, the file named by files-service."""
    found = [
        s
        for s in steps
        if executor_of(nodes.get(str(s["nodeId"]))) == READ
        and s.get("status") == "ok"
        and s.get("port") in READ_PORTS
        and engine_reviews.is_read(s.get("output"))
    ]
    # The name a file arrived with, as the run's input gives it; files-service keeps one file per bytes, so its name is
    # the first upload's and only fills in a file the input does not name.
    given = {f["id"]: f["name"] for f in files_in(run_input)}
    wanted = [str(cast(dict[str, Any], s["output"])["fileId"]) for s in found]
    files = await named(rt, team, [{"id": i, "name": given.get(i)} for i in wanted])
    return [
        {
            "nodeId": str(s["nodeId"]),
            "name": _name(nodes.get(str(s["nodeId"])), str(s["nodeId"])),
            "read": engine_reviews.read_view(cast(dict[str, Any], s["output"]), f.get("name"), None),
        }
        for s, f in zip(found, files, strict=True)
    ]


def started_entries(steps: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """The runs the Start workflow steps started, each `{nodeId, index, runId, label}`, the first MAX_CHILDREN per step;
    and how many more there were."""
    out: list[dict[str, Any]] = []
    more = 0
    for s in steps:
        o = s.get("output")
        if executor_of(nodes.get(str(s["nodeId"]))) != START or not isinstance(o, dict):
            continue
        given = cast(dict[str, Any], o)
        raw = cast(list[Any], given.get("runs") or given.get("children") or [])
        listed = [cast(dict[str, Any], r) for r in raw if isinstance(r, dict) and cast(dict[str, Any], r).get("runId")]
        more += max(0, len(listed) - MAX_CHILDREN)
        out += [
            {
                "nodeId": str(s["nodeId"]),
                "index": int(r.get("index", i)),
                "runId": str(r["runId"]),
                "label": r.get("label"),
            }
            for i, r in enumerate(listed[:MAX_CHILDREN])
        ]
    return out, more


def _ending(steps: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]) -> tuple[str | None, str | None]:
    """The End step a run finished on and the last step it ran, by name."""
    ends = [s for s in steps if nodes.get(str(s["nodeId"]), {}).get("type") == END and s.get("status") == "ok"]
    end = _name(nodes.get(str(ends[-1]["nodeId"])), str(ends[-1]["nodeId"])) if ends else None
    failed = [s for s in steps if s.get("status") not in ("ok", "running")]
    last = failed[-1] if failed else (steps[-1] if steps else None)
    return end, _name(nodes.get(str(last["nodeId"])), str(last["nodeId"])) if last else None


def _option_label(node: dict[str, Any] | None, decision: str) -> str:
    for o in cast(list[Any], cast(dict[str, Any], (node or {}).get("parameters") or {}).get("options") or []):
        if isinstance(o, dict) and cast(dict[str, Any], o).get("name") == decision:
            return str(cast(dict[str, Any], o).get("label") or words(decision))
    return words(decision)


def state_of(child: dict[str, Any], ending: str | None, last: str | None, open_task: bool) -> str:
    """Where a run is now, in words: the End step's name once it finished, or what it waits for."""
    status = str(child["status"])
    if status == "succeeded":
        return ending or words(str(child.get("outcome") or "finished"))
    if status == "failed":
        return f"Failed at {last}" if last else "Failed"
    if status == "cancelled":
        return "Cancelled"
    if open_task:
        return "Waiting for a person"
    if status == "waiting":
        return "Waiting on the runs it started"
    return "Not started yet" if status == "queued" else "Running"


def _facts(fields: dict[str, Any]) -> list[dict[str, str]]:
    """A case's own fields as labelled text: a list reads as each item's first text that is not an id."""
    out: list[dict[str, str]] = []
    for key, value in fields.items():
        text = first_text(value) if isinstance(value, (dict, list)) else (None if value is None else str(value))
        if text:
            out.append({"label": words(re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key)).capitalize(), "value": text})
    return out


async def children_of(
    rt: Runtime, run: dict[str, Any], steps: list[dict[str, Any]], nodes: dict[str, dict[str, Any]], *, scope: Any
) -> tuple[list[dict[str, Any]], int]:
    """The runs this run's steps started, as rows a person reads, and how many more there were. Every read is one
    query for all of them: their runs, steps, pinned definitions, cases and who their open tasks wait for."""
    started, more = started_entries(steps, nodes)
    store = RunStore(EngineTransactions(rt.db))
    found = {str(r["id"]): r for r in await store.many([c["runId"] for c in started])}
    # A run of another team is never told, whatever started it.
    started = [c for c in started if c["runId"] in found and found[c["runId"]]["team_id"] == run["team_id"]]
    ids = [c["runId"] for c in started]
    steps_by_run = {rid: steps_view(rows) for rid, rows in (await store.steps_of(ids)).items()}
    pinned = await DefinitionStore(EngineTransactions(rt.db)).pinned(
        {(str(found[i]["workflow_id"]), int(found[i]["version"])) for i in ids}
    )
    cases = CaseStore(rt.db)
    on_case = await cases.cases_of_runs(ids)
    summaries = await cases.summaries(list(dict.fromkeys(on_case.values())), [str(run["team_id"])])
    assigned = await ReviewAssignments(rt.db).current() if ids else {}
    decided = {rid: decisions_in(rid, steps_by_run.get(rid, [])) for rid in ids}
    people = await actors(
        rt,
        [*(d["by"] for ds in decided.values() for d in ds if d["by"]), *assigned.values()],
    )
    own_nodes = nodes_of({"definition": {"nodes": list(nodes.values())}})
    rows: list[dict[str, Any]] = []
    for c in started:
        child = found[c["runId"]]
        stored = pinned.get((str(child["workflow_id"]), int(child["version"])))
        child_nodes = nodes_of(stored)
        child_steps = steps_by_run.get(c["runId"], [])
        workflow = workflow_name(stored)
        row: dict[str, Any] = {
            "runId": c["runId"],
            "nodeId": c["nodeId"],
            "index": c["index"],
            "workflowName": workflow,
            "stepName": _name(own_nodes.get(c["nodeId"]), c["nodeId"]),
            "label": str(c["label"] or workflow),
            "status": child["status"],
            "outcome": child.get("outcome"),
        }
        if scope is not None and scope != ("workflow", child["workflow_id"]):
            # A key scoped to one workflow reads another workflow's runs by status alone.
            rows.append(
                row
                | {
                    "label": workflow,
                    "ending": None,
                    "cases": [],
                    "tasks": [],
                    "state": state_of(child, None, None, False),
                }
            )
            continue
        tasks: list[dict[str, Any]] = []
        for d in decided[c["runId"]]:
            node = child_nodes.get(d["nodeId"])
            title = _name(node, d["nodeId"])
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
        waiting = cast(dict[str, Any] | None, child.get("waiting"))
        open_task = bool(waiting) and executor_of(child_nodes.get(str((waiting or {}).get("node")))) == REVIEW
        if waiting and open_task:
            node = child_nodes.get(str(waiting["node"]))
            payload = cast(dict[str, Any], waiting.get("payload") or {})
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
        row |= {
            "ending": ending if child["status"] == "succeeded" else None,
            "state": state_of(child, ending, last, open_task),
            "cases": [
                {
                    "caseId": case_id,
                    "subject": summary["subject"],
                    "customer": summary["customer"],
                    "facts": _facts(summary["fields"]),
                }
            ]
            if case_id and summary
            else [],
            "tasks": tasks,
        }
        rows.append(row)
    return rows, more


def masked_story(value: Any, key: str | None = None) -> Any:
    """The story as people read it with masking on: every text but ids and enum words masked."""
    if key in _KEEP:
        return value
    if isinstance(value, dict):
        return {k: masked_story(v, k) for k, v in cast(dict[str, Any], value).items()}
    if isinstance(value, list):
        return [masked_story(v) for v in cast(list[Any], value)]
    return masked(value) if isinstance(value, str) else value


# Where an email came from and arrived (`shapes.EMAIL`): channel metadata, shown with masking on. What the email and
# its documents say (subject, body, every value read) is content, masked like any other run data.
CHANNEL_FIELDS = ("from", "mailbox")


async def channel_addresses(rt: Runtime, run: dict[str, Any]) -> set[str]:
    """The sender and mailbox of the email that started this run or, for a run another run started, its family's."""
    store, defs = RunStore(EngineTransactions(rt.db)), DefinitionStore(EngineTransactions(rt.db))
    for here in [run, *await runs_above(store, run)]:
        email = email_of(here, nodes_of(await defs.get(str(here["workflow_id"]), here.get("version"))))
        if email is not None:
            return {str(email[k]) for k in CHANNEL_FIELDS if email.get(k)}
    return set()


def keep_channel(shown: Any, real: Any, addresses: set[str]) -> Any:
    """`shown` (masked) with every value that is one of `addresses` put back as it really reads."""
    if not addresses:
        return shown
    if isinstance(real, str):
        return real if real in addresses else shown
    if isinstance(real, dict) and isinstance(shown, dict):
        r, s = cast(dict[str, Any], real), cast(dict[str, Any], shown)
        return {k: keep_channel(v, r.get(k), addresses) if k in r else v for k, v in s.items()}
    if isinstance(real, list) and isinstance(shown, list) and len(cast(list[Any], real)) == len(cast(list[Any], shown)):
        return [
            keep_channel(v, x, addresses) for v, x in zip(cast(list[Any], shown), cast(list[Any], real), strict=True)
        ]
    return cast(Any, shown)


TOOL = "gateway.call"
AI_STEPS = ("kernel.turn", "ai.prompt")
CASE_OPEN, CASE_ADD = "case.open", "case.add"
# The platform's reply operation (tools-service PLATFORM_TOOLS): a call to it is an email the run sent.
REPLY_TOOL = "send_reply"
DECIDED = {"approve": "approved", "reject": "rejected"}


def _attempt_at(step: dict[str, Any], key: str) -> str | None:
    attempts = cast(list[dict[str, Any]], step.get("attempts") or [])
    at = attempts[-1].get(key) if attempts else None
    return at.isoformat() if isinstance(at, datetime) else (str(at) if at else None)


def _line(at: Any, source: str, actor: str, text: str, href: str | None) -> dict[str, Any]:
    return {"at": str(at) if at else None, "source": source, "actor": actor, "text": text, "href": href}


def tool_calls(steps: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Each tool step's call, keyed `<nodeId>:<iteration>`, for describe_calls to word once per page."""
    out: dict[str, dict[str, Any]] = {}
    for st in steps:
        given = st.get("input")
        if executor_of(nodes.get(str(st["nodeId"]))) == TOOL and isinstance(given, dict):
            g = cast(dict[str, Any], given)
            out[f"{st['nodeId']}:{st['iteration']}"] = {
                "tool": str(g.get("operation") or ""),
                "input": g.get("input") or {},
            }
    return out


def actors_in(run: dict[str, Any], steps: list[dict[str, Any]]) -> list[str]:
    """Who a run's lines name, raw, for one actors() call: who started it and each person who decided a step."""
    return [started_by_of(run), *(str(d["by"]) for d in decisions_in(str(run["id"]), steps) if d["by"])]


def _read_text(read: dict[str, Any], names: dict[str, str]) -> str:
    records = cast(
        list[dict[str, Any]], read.get("records") or ([{"fields": read["fields"]}] if read.get("fields") else [])
    )
    fields = [cast(dict[str, Any], f) for r in records for f in cast(dict[str, Any], r.get("fields") or {}).values()]
    check = sum(1 for f in fields if f.get("needsReview"))
    name = names.get(str(read.get("fileId") or "")) or "the document"
    counted = f"{plural(len(records), 'record')}, {plural(len(fields), 'field')}"
    return f"Read {name}: {counted}" + (f", {check} to check" if check else "")


def _review_title(run: dict[str, Any], step: dict[str, Any], node: dict[str, Any] | None, fallback: str) -> str:
    """A Human Task step's title as it was asked: the resolved title the step journaled or the run waits on, else the
    node's own title when it holds no expression, else the step's name; never an unresolved `{$...}`."""
    given = cast(dict[str, Any], step.get("input") or {}) if isinstance(step.get("input"), dict) else {}
    waiting = cast(dict[str, Any], run.get("waiting") or {})
    payload = cast(dict[str, Any], waiting.get("payload") or {}) if waiting.get("node") == step.get("nodeId") else {}
    param = cast(dict[str, Any], (node or {}).get("parameters") or {}).get("title")
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


def masked_lines(told: list[dict[str, Any]], keep: set[str]) -> list[dict[str, Any]]:
    """Story lines as people read them with masking on: text and actor masked, the channel addresses kept."""
    return [
        line | {"text": masked_keeping(str(line["text"]), keep), "actor": masked_keeping(str(line["actor"]), keep)}
        for line in told
    ]


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def lines(
    run: dict[str, Any],
    steps: list[dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    *,
    workflow: str,
    team: str,
    calls: dict[str, dict[str, Any]],
    who: dict[str, dict[str, Any]],
    started: dict[str, str] | None = None,
    started_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """What a run did, one plain sentence per line, oldest first: `{at, source, actor, text, href}`. Each step is
    worded by its node's executor, the recognition `story()` uses, never by a node id or a workflow's own words; tool
    calls by `calls` (describe_calls) and people by `who` (actors). `started` is the runs its steps started that the
    reader may see, by id, with the label they may read (children_of's rows); a run outside it is neither named nor
    counted. The one wording of a run's steps: every page that tells what a run did draws these lines."""
    run_id = str(run["id"])
    page = f"/workflows/runs/{run_id}"
    out: list[dict[str, Any]] = []
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
        via = cast(dict[str, Any], starter.get("via") or {})
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
        o = cast(dict[str, Any], output) if isinstance(output, dict) else {}
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
            g = cast(dict[str, Any], st.get("input") or {})
            if g.get("operation") == REPLY_TOOL and not failed:
                given = cast(dict[str, Any], g.get("input") or {})
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
            given = cast(dict[str, Any], st.get("input") or {})
            href = f"/cases/{o['caseId']}" if o.get("caseId") else None
            out.append(
                _line(finished, "automation", workflow, f"Opened a case: {given.get('subject') or step_name}", href)
            )
        elif executor == CASE_ADD and not failed:
            given = cast(dict[str, Any], st.get("input") or {})
            added = ", ".join(humanize(str(k)).lower() for k in cast(dict[str, Any], given.get("fields") or {}))
            out.append(_line(finished, "automation", workflow, f"Added {added or 'details'} to the case", page))
        elif executor == START and not failed:
            runs = cast(list[dict[str, Any]], o.get("runs") or o.get("children") or [])
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
    return [out[0], *sorted(out[1:], key=lambda x: x["at"] or "")]


async def story(
    rt: Runtime, run: dict[str, Any], steps: list[dict[str, Any]], *, scope: Any, masking: bool
) -> dict[str, Any]:
    """The run told for people: `email`, `reads` and `children` (with `childrenMore`), from the version it pinned."""
    stored = await DefinitionStore(EngineTransactions(rt.db)).get(str(run["workflow_id"]), run.get("version"))
    nodes = nodes_of(stored)
    children, more = await children_of(rt, run, steps, nodes, scope=scope)
    team = str(run["team_id"])
    names = getattr(rt, "team_names", None)
    told = {
        "workflowName": workflow_name(stored),
        "email": email_of(run, nodes),
        "reads": await reads_of(rt, team, steps, nodes, run.get("input")),
        "children": children,
        "childrenMore": more,
        "lines": lines(
            run,
            steps,
            nodes,
            workflow=workflow_name(stored),
            team=(await names.name(team) if names is not None else None) or team,
            calls=await describe_calls(rt, tool_calls(steps, nodes)),
            who=await actors(rt, actors_in(run, steps)),
            started={str(c["runId"]): str(c["label"]) for c in children},
            started_names={str(c["runId"]): str(c["workflowName"]) for c in children},
        ),
    }
    return masked_story(told) if masking else told
