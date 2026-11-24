"""`opsai workflows` over the public SDK: validate, apply, publish, run, watch, inspect, decide."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from ops_ai._io import definition_in, dump_definition, load_definition
from ops_ai._workflows import PLANNED, WorkflowCheck

from .common import client, emit, parser, payload, refuse, table

STARTER = """schemaVersion: 2
id: {id}
name: {name}
nodes:
  - id: start
    type: ops.trigger.request
    typeVersion: 1
    name: Request
    parameters:
      inputSchema:
        type: object
        properties:
          message: {{ type: string }}
  - id: done
    type: ops.flow.end
    typeVersion: 1
    name: Done
    parameters: {{ outcome: done }}
connections:
  - from: {{ node: start, port: payload }}
    to: {{ node: done, port: in }}
"""


def main(argv: list[str]) -> int:
    ap = parser("opsai workflows", "Author and run workflows through the public SDK.")
    sub = ap.add_subparsers(dest="verb", required=True)
    init = sub.add_parser("init", help="create a generic workflow folder")
    init.add_argument("folder")
    init.add_argument("--from", dest="source")
    convert = sub.add_parser("convert", help="write YAML or JSON")
    convert.add_argument("file")
    convert.add_argument("--to", choices=("yaml", "json"), required=True)
    convert.add_argument("-o", "--output")
    types = sub.add_parser("types", help="list node types")
    types.add_argument("--group")
    type_one = sub.add_parser("type", help="show one node type")
    type_one.add_argument("id")
    for name, help_text in (
        ("validate", "print checks"),
        ("plan", "validate and diff without saving"),
        ("apply", "store the next draft"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("definition")
    export = sub.add_parser("export", help="print a stored definition")
    export.add_argument("id")
    export.add_argument("--format", choices=("yaml", "json"), default="yaml")
    save_copy = sub.add_parser("save-copy", help="save a definition as the working copy; makes no version")
    save_copy.add_argument("id")
    save_copy.add_argument("definition")
    diff = sub.add_parser("diff", help="what changed between two versions, live or the working copy")
    diff.add_argument("id")
    diff.add_argument("--from", dest="from_", default="live")
    diff.add_argument("--to", default="working-copy")
    publish = sub.add_parser("publish", help="request or complete publish")
    publish.add_argument("id")
    publish.add_argument("--note", default="")
    publish.add_argument("--working-copy", action="store_true", help="publish the working copy in one call")
    for name in ("pause", "archive"):
        sub.add_parser(name, help=f"{name} a definition").add_argument("id")
    run = sub.add_parser("run", help="start a run; test is the default")
    run.add_argument("id")
    run.add_argument("--input")
    run.add_argument("--event")
    run.add_argument("--test", action="store_true", default=True)
    run.add_argument("--live", action="store_true")
    run.add_argument("--wait", action="store_true")
    email = sub.add_parser("send-test-email", help="start from an email trigger's test form")
    email.add_argument("id")
    email.add_argument("--event", required=True)
    listing = sub.add_parser("list", help="the team's workflows, every page")
    listing.add_argument("--search")
    listing.add_argument("--status", action="append", help="draft, live, paused, in_review or archived")
    forms = sub.add_parser("forms", help="a workflow's hosted forms")
    forms.add_argument("id")
    forms.add_argument("--search")
    start = sub.add_parser("batch-start", help="start a batch over an uploaded file's rows")
    start.add_argument("id")
    start.add_argument("--file-id", required=True, help="the uploaded file (opsai files upload)")
    start.add_argument("--dry-run", action="store_true")
    start.add_argument("--live", action="store_true")
    batch = sub.add_parser("batch", help="one run per CSV or JSON row")
    batch.add_argument("id")
    batch.add_argument("--file", required=True)
    batch.add_argument("--dry-run", action="store_true")
    batch.add_argument("--live", action="store_true")
    sub.add_parser("form", help="hosted start form (planned)").add_argument("rest", nargs=argparse.REMAINDER)
    watch = sub.add_parser("watch", help="stream run events")
    watch.add_argument("run_id")
    inspect = sub.add_parser("inspect", help="show a run")
    inspect.add_argument("run_id")
    trace = sub.add_parser("trace", help="show the run timeline")
    trace.add_argument("run_id")
    trace.add_argument("--format", choices=("text", "json"), default="text")
    test = sub.add_parser("test", help="run fixture cases from a folder")
    test.add_argument("source")
    test.add_argument("--case")
    sub.add_parser("eval", help="dataset evaluation (planned)").add_argument("source")
    replay = sub.add_parser("replay", help="replay a run (planned)")
    replay.add_argument("run_id")
    fork = sub.add_parser("fork", help="fork from a node (planned)")
    fork.add_argument("run_id")
    fork.add_argument("--from", dest="from_node", required=True)
    retry = sub.add_parser("retry", help="retry a stuck run")
    retry.add_argument("run_id")
    sched = sub.add_parser("schedule", help="a trigger's saved schedule: show, set, clear, kinds, preview")
    sched.add_argument("action", choices=("show", "set", "clear", "kinds", "preview"))
    sched.add_argument("id", nargs="?", help="the workflow (show, set, clear)")
    sched.add_argument("--step", help="the trigger step's id (show, set, clear)")
    sched.add_argument("--kind", help="the rule kind (opsai workflows schedule kinds)")
    sched.add_argument(
        "--set",
        dest="fields",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="a field of the kind; VALUE is JSON or text",
    )
    sched.add_argument("--rule", help="the whole rule as JSON or @file, instead of --kind and --set")
    decide = sub.add_parser("decide", help="decide a human task")
    decide.add_argument("task_id")
    decide.add_argument("choice")
    decide.add_argument("--fields")
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns)
    except (OSError, ValueError, KeyError) as exc:
        return refuse(exc)
    except Exception as exc:
        return refuse(exc)


def _dispatch(ns: argparse.Namespace) -> int:
    if ns.verb == "init":
        return _init(ns)
    if ns.verb == "convert":
        return _convert(ns)
    if ns.verb == "form":
        sys.stderr.write(f"{PLANNED}\n")
        return 2
    ops = client(ns)
    wf = ops.workflows
    if ns.verb == "types":
        return emit(ns, wf.types(group=ns.group))
    if ns.verb == "type":
        return emit(ns, wf.type(ns.id))
    if ns.verb == "validate":
        check = wf.validate(definition_in(ns.definition))
        return _check(ns, check)
    if ns.verb == "plan":
        return emit(ns, wf.plan(definition_in(ns.definition)))
    if ns.verb == "apply":
        made = wf.apply(definition_in(ns.definition))
        return emit(
            ns,
            made,
            text=f"{made.get('workflowId')} v{made.get('version')} {made.get('digest')} "
            f"{'created' if made.get('created') else 'unchanged'}",
        )
    if ns.verb == "export":
        return emit(ns, wf.export(ns.id, format=ns.format), text=wf.export(ns.id, format=ns.format))
    if ns.verb == "save-copy":
        saved = wf.save_working_copy(ns.id, definition_in(ns.definition))
        errors = [c for c in saved["workingCopy"]["checks"] if c.get("level") == "error"]
        return emit(ns, saved, text=f"{ns.id} working copy saved, {len(errors)} problem(s)")
    if ns.verb == "diff":
        changes = wf.diff(ns.id, from_=ns.from_, to=ns.to)
        return emit(ns, changes, text=_diff_text(changes))
    if ns.verb == "publish":
        review = wf.publish(ns.id, note=ns.note, working_copy=ns.working_copy)
        stage = "waiting for review" if review.get("id") and not review.get("liveVersion") else "live"
        return emit(ns, review, text=f"{ns.id} {stage}")
    if ns.verb == "pause":
        return emit(ns, wf.pause(ns.id))
    if ns.verb == "archive":
        return emit(ns, wf.archive(ns.id))
    if ns.verb == "run":
        mode = "live" if ns.live else "test"
        if ns.event:
            started = wf.send_test_email(ns.id, ns.event, mode=mode)
            return emit(ns, ops.runs.wait(started["runId"]) if ns.wait else started)
        return emit(ns, wf.run(ns.id, input=payload(ns.input), mode=mode, wait=ns.wait))
    if ns.verb == "send-test-email":
        return emit(ns, wf.send_test_email(ns.id, ns.event))
    if ns.verb == "list":
        return table(ns, wf.list(search=ns.search, status=ns.status), "workflowId", "name", "status", "version")
    if ns.verb == "forms":
        return table(ns, wf.forms(ns.id, search=ns.search), "id", "title", "slug", "paused")
    if ns.verb == "batch-start":
        mode = "live" if ns.live else "test"
        return emit(ns, wf.start_batch(ns.id, ns.file_id, mode=mode, dry_run=ns.dry_run or None))
    if ns.verb == "batch":
        return emit(ns, wf.batch(ns.id, ns.file, mode="live" if ns.live else "test", dry_run=ns.dry_run))
    if ns.verb == "watch":
        last = None
        for event in ops.runs.stream(ns.run_id):
            last = event
            if not ns.quiet:
                sys.stdout.write(f"{event.get('type') or event.get('status') or event}\n")
        return emit(ns, last or {}, text="") if ns.as_json else 0
    if ns.verb == "inspect":
        return emit(ns, ops.runs.get(ns.run_id))
    if ns.verb == "trace":
        traced = wf.trace(ns.run_id)
        if ns.format == "json" or ns.as_json:
            return emit(argparse.Namespace(**{**vars(ns), "as_json": True}), traced)
        return emit(ns, traced, text=_trace_text(traced))
    if ns.verb == "test":
        results = wf.test(ns.source, case=ns.case)
        failed = [r for r in results if not r["ok"]]
        text = f"{len(results) - len(failed)}/{len(results)} passed"
        code = emit(ns, results, text=text)
        return 1 if failed else code
    if ns.verb in {"eval", "replay", "fork"}:
        sys.stderr.write(f"{PLANNED}\n")
        return 2
    if ns.verb == "retry":
        return emit(ns, ops.runs.retry(ns.run_id))
    if ns.verb == "schedule":
        return _schedule(ns, wf.schedules)
    if ns.verb == "decide":
        return emit(ns, ops.tasks.decide(ns.task_id, ns.choice, **(payload(ns.fields) or {})))
    return 2


def _init(ns: argparse.Namespace) -> int:
    dest = Path(ns.folder)
    if dest.exists() and any(dest.iterdir()):
        sys.stderr.write(f"{dest} is not empty\n")
        return 2
    dest.mkdir(parents=True, exist_ok=True)
    if ns.source:
        shutil.copytree(ns.source, dest, dirs_exist_ok=True)
        return emit(ns, {"folder": str(dest)}, text=str(dest))
    (dest / "resources").mkdir(exist_ok=True)
    (dest / "fixtures").mkdir(exist_ok=True)
    (dest / "expected").mkdir(exist_ok=True)
    name = dest.name.replace("-", " ")
    (dest / "resources" / "workflow.yaml").write_text(STARTER.format(id=dest.name.replace("-", "_"), name=name))
    return emit(ns, {"folder": str(dest)}, text=str(dest))


def _convert(ns: argparse.Namespace) -> int:
    data = load_definition(definition_in(ns.file))
    text = dump_definition(data, ns.to)
    if ns.output:
        Path(ns.output).write_text(text)
        return 0
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def _diff_text(changes: dict[str, Any]) -> str:
    """One line per step: + added, - removed, ~ changed with each setting, > moved."""
    lines = [f"+ {s['name']}" for s in changes["added"]] + [f"- {s['name']}" for s in changes["removed"]]
    for step in changes["changed"]:
        lines.append(f"~ {step['name']}: " + ", ".join(f["field"] for f in step["fields"]))
    lines += [f"> {s['name']} moved" for s in changes["moved"]]
    return "\n".join(lines) or "no step changed"


def _check(ns: argparse.Namespace, check: WorkflowCheck) -> int:
    emit(ns, dict(check), text=_checks_text(check))
    return 0 if check.ok else 1


def _checks_text(check: WorkflowCheck) -> str:
    if check.ok:
        return f"valid {check.get('workflowId') or ''} {check.get('digest') or ''}".strip()
    lines = []
    for item in check.checks:
        where = item.get("path") or item.get("node") or item.get("code")
        lines.append(f"{item.get('level', 'error')} {where}: {item.get('message')}")
        if item.get("suggestion"):
            lines.append(f"  {item['suggestion']}")
    return "\n".join(lines)


def _trace_text(traced: dict[str, Any]) -> str:
    run = traced.get("run") or {}
    lines = [f"{run.get('id')} {run.get('status')} {run.get('outcome') or ''}"]
    if traced.get("failure"):
        fail = traced["failure"]
        lines.append(f"failure {fail.get('nodeId') or ''}: {fail.get('message')}")
    for step in traced.get("steps") or []:
        lines.append(f"{step.get('nodeId')} {step.get('status')} {step.get('port') or ''}".strip())
    return "\n".join(lines)


def _rule_fields(ns: argparse.Namespace) -> dict[str, Any]:
    """The kind and its own fields from `--rule` or `--kind` with `--set`; each VALUE is read as JSON, else text."""
    if ns.rule:
        rule = payload(ns.rule)
        if not isinstance(rule, dict) or "kind" not in rule:
            raise ValueError("--rule is an object with a kind")
        return rule
    if not ns.kind:
        raise ValueError("name the rule's kind with --kind, or give the whole rule with --rule")
    fields: dict[str, Any] = {"kind": ns.kind}
    for pair in ns.fields:
        name, sep, raw = pair.partition("=")
        if not sep or not name:
            raise ValueError(f"--set takes FIELD=VALUE, not {pair}")
        try:
            fields[name] = json.loads(raw)
        except ValueError:
            fields[name] = raw
    return fields


def _schedule(ns: argparse.Namespace, schedules: Any) -> int:
    if ns.action == "kinds":
        return table(ns, schedules.kinds(), "name", "label")
    if ns.action == "preview":
        shown = schedules.preview(**_rule_fields(ns))
        runs = "\n".join(f"  {t}" for t in shown["nextRuns"])
        return emit(ns, shown, text=f"{shown['words']}\nNext runs:\n{runs}")
    if not ns.id or not ns.step:
        raise ValueError("name the workflow and its trigger step: schedule <action> <workflow> --step <step>")
    if ns.action == "show":
        got = schedules.show(ns.id, ns.step)
        return emit(ns, got, text=_schedule_text(got))
    if ns.action == "clear":
        schedules.clear(ns.id, ns.step)
        return emit(ns, {"cleared": True}, text=f"{ns.id} {ns.step}: schedule cleared")
    saved = schedules.save(ns.id, ns.step, **_rule_fields(ns))
    return emit(ns, saved, text=_schedule_text(saved))


def _schedule_text(view: dict[str, Any]) -> str:
    runs = ", ".join(view.get("nextRuns") or []) or "none"
    last = view.get("lastOutcome") or "not run yet"
    return f"{view['words']}\nNext runs: {runs}\nLast: {last}; changed by {view['changedBy']} at {view['changedAt']}"
