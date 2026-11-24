"""`opsai batches`: one batch of a workflow, a spreadsheet's rows or one check of a watched folder. `get` prints its
counts and rows, failed first; `retry` starts its failed runs again; `csv` writes its results. `opsai workflows batches
<workflow>` lists a workflow's batches."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ops_ai import OpsAI

from .common import client, emit, parser, refuse, verb_options


def _counts(batch: dict[str, object]) -> str:
    said = ", ".join(f"{batch.get(k)} {k}" for k in ("finished", "running", "waiting", "pending", "failed", "removed"))
    return f"{batch.get('fileName')}: {batch.get('total')} rows; {said}"


def main(argv: list[str]) -> int:
    ap = parser("opsai batches", "A workflow's batch: get, retry, csv.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    sub.add_parser("get", parents=common, help="a batch's counts and rows, failed first").add_argument("id")
    sub.add_parser("retry", parents=common, help="start the failed runs again").add_argument("id")
    csv = sub.add_parser("csv", parents=common, help="the results, one line per row")
    csv.add_argument("id")
    csv.add_argument("--out", help="write to this file instead of the screen")
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns, client(ns))
    except Exception as exc:
        return refuse(exc)


def _dispatch(ns: argparse.Namespace, ops: OpsAI) -> int:
    if ns.verb == "retry":
        done = dict(ops.workflows.retry_batch(ns.id))
        said = f"{done.get('retried')} started again; {done.get('notRetryable')} cannot be retried"
        return emit(ns, done, text=said)
    if ns.verb == "csv":
        text = ops.workflows.batch_csv(ns.id)
        if not ns.out:
            sys.stdout.write(text)
            return 0
        Path(ns.out).write_text(text, encoding="utf-8")
        return emit(ns, {"written": ns.out}, text=f"wrote {ns.out}")
    batch = ops.workflows.get_batch(ns.id)
    return emit(ns, batch, text=_counts(dict(batch)))
