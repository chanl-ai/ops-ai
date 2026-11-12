"""`opsai runs` and `opsai tasks`: workflow runs as the Runs page shows them (start, status, events as they happen,
cancel, retry), and Human Tasks as the Human Tasks queue shows them (list, open one, decide it)."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from ops_ai import OpsAI
from ops_ai._transport import page_items

from .common import client, emit, parser, payload, refuse, short, table, verb_options


def runs_main(argv: list[str]) -> int:
    ap = parser("opsai runs", "Start and follow workflow runs.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    listing = sub.add_parser("list", parents=common, help="runs, newest first")
    listing.add_argument("--workflow")
    listing.add_argument("--status", action="append")
    start = sub.add_parser("start", parents=common, help="start a run of a workflow's current version; test by default")
    start.add_argument("workflow")
    start.add_argument("--input", help="the input: k=v,k=v, JSON, a file, or - for standard input")
    start.add_argument("--live", action="store_true", help="a live run, which reaches real systems")
    start.add_argument("--wait", action="store_true", help="wait until it ends or stops at a Human Task")
    for name, text in (
        ("show", "a run's status"),
        ("events", "a run's events as they happen, until it ends or waits"),
        ("cancel", "cancel a run"),
        ("retry", "queue a Stuck run again from its last step"),
    ):
        sub.add_parser(name, parents=common, help=text).add_argument("run")
    ns = ap.parse_args(argv)
    try:
        return _runs(ns, client(ns))
    except Exception as exc:
        return refuse(exc)


def _runs(ns: argparse.Namespace, ops: OpsAI) -> int:
    if ns.verb == "list":
        found = ops.raw.agents.workflows_list_engine_runs(workflow_id=ns.workflow, status=ns.status, page_size=50)
        return table(ns, page_items(found)[0], "id", "workflowId", "mode", "status", "outcome", "createdAt")
    if ns.verb == "start":
        started = ops.runs.start(ns.workflow, input=payload(ns.input), mode="live" if ns.live else "test")
        if ns.wait:
            done = ops.runs.wait(str(started["runId"]))
            return emit(ns, done, text=_status(done))
        return emit(ns, started, text=f"{started.get('runId')} started")
    if ns.verb == "show":
        run = ops.runs.get(ns.run)
        return emit(ns, run, text=_status(run))
    if ns.verb == "events":
        seen = []
        for event in ops.runs.stream(ns.run):
            e = event.get("data") if isinstance(event.get("data"), dict) else event
            seen.append(e)
            if not ns.as_json and not ns.quiet:
                sys.stdout.write(event_line(e) + "\n")
                sys.stdout.flush()
        return emit(ns, seen) if ns.as_json else 0
    if ns.verb == "cancel":
        return emit(ns, ops.runs.cancel(ns.run))
    if ns.verb == "retry":
        return emit(ns, ops.runs.retry(ns.run))
    return 2


def event_line(e: dict[str, Any]) -> str:
    """One run event as the run page's timeline shows it: when, what, which step, and the step's detail."""
    detail = dict(e.get("data") or {})
    phase = detail.pop("phase", "")
    rest = short(detail, 120) if detail else ""
    return " ".join(str(p) for p in (e.get("seq"), e.get("at"), e.get("type"), e.get("node") or "", phase, rest) if p)


def _status(run: dict[str, Any]) -> str:
    task = f" task {run['taskId']}" if run.get("taskId") else ""
    return f"{run.get('id')} {run.get('status')} {run.get('outcome') or ''}{task}".strip()


def tasks_main(argv: list[str]) -> int:
    ap = parser("opsai tasks", "Human Tasks: list, open, decide.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    listing = sub.add_parser("list", parents=common, help="the Human Tasks queue")
    listing.add_argument("--view", help="the queue's tab, e.g. mine, open, done")
    listing.add_argument("--search")
    sub.add_parser("show", parents=common, help="one task").add_argument("task")
    decide = sub.add_parser("decide", parents=common, help="send one of the actions the task offers")
    decide.add_argument("task")
    decide.add_argument("decision", help="the action, e.g. approve or reject")
    decide.add_argument("--reason")
    decide.add_argument("--fields", help="the task's form fields: k=v,k=v, JSON, a file, or -")
    approve = sub.add_parser("approve", parents=common, help="approve a task, such as a write a chat held")
    approve.add_argument("task")
    approve.add_argument("--reason")
    approve.add_argument(
        "--password", help="the approver's password for the step-up a write asks for (or OPS_PASSWORD)"
    )
    ns = ap.parse_args(argv)
    try:
        return _tasks(ns, client(ns))
    except Exception as exc:
        return refuse(exc)


def _tasks(ns: argparse.Namespace, ops: OpsAI) -> int:
    if ns.verb == "list":
        found = ops.raw.agents.reviews_list_reviews(view=ns.view, search=ns.search, page_size=50)
        return table(ns, page_items(found)[0], "id", "kind", "title", "risk", "status")
    if ns.verb == "show":
        return emit(ns, ops.tasks.get(ns.task))
    if ns.verb == "decide":
        fields = payload(ns.fields) if ns.fields else {}
        inputs = {"inputs": fields} if fields else {}
        return emit(ns, ops.tasks.decide(ns.task, ns.decision, reason=ns.reason, **inputs))
    if ns.verb == "approve":
        password = ns.password or os.environ.get("OPS_PASSWORD")
        return emit(ns, ops.tasks.approve(ns.task, password=password, reason=ns.reason))
    return 2
