"""`opsai batches`: one batch of a workflow, a spreadsheet's rows or one check of a watched folder. `get` prints its
counts and rows, failed first; `opsai workflows batches <workflow>` lists a workflow's batches."""

from __future__ import annotations

import argparse

from ops_ai import OpsAI

from .common import client, emit, parser, refuse, verb_options


def _counts(batch: dict[str, object]) -> str:
    said = ", ".join(f"{batch.get(k)} {k}" for k in ("finished", "running", "waiting", "pending", "failed", "removed"))
    return f"{batch.get('fileName')}: {batch.get('total')} rows; {said}"


def main(argv: list[str]) -> int:
    ap = parser("opsai batches", "A workflow's batch: get.")
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("get", parents=[verb_options()], help="a batch's counts and rows, failed first").add_argument("id")
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns, client(ns))
    except Exception as exc:
        return refuse(exc)


def _dispatch(ns: argparse.Namespace, ops: OpsAI) -> int:
    batch = ops.workflows.get_batch(ns.id)
    return emit(ns, batch, text=_counts(dict(batch)))
