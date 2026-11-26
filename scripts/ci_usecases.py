#!/usr/bin/env python3
"""Which use cases CI runs, and a run that honours the quarantine.

    ci_usecases.py pick [--base REF] [--head REF]        use case ids the changed files affect, one per line
    ci_usecases.py all [--shard I/N]                     every runnable use case, or the Ith of N slices of them
    ci_usecases.py run [--shard I/N] [--slots N] [--out FILE] [--no-gate] ID...
    ci_usecases.py --self-test

`pick` is scripts/agents/affected_usecases.py (the file-to-use-case map `make agent-affected-usecases` prints) cut down
to the use cases that have a script and are not retired. `run` runs each id with scripts/usecase_batch.py, so the slot
guard and per-run databases still apply, prints one line per id, writes the result as JSON, and exits 1 only for a
failure that config/quarantine.json does not cover. A quarantined failure is printed and recorded as "quarantined".
Stdlib only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "agents"))

import affected_usecases  # noqa: E402
import quarantine  # noqa: E402
import usecase_batch  # noqa: E402

REGISTRY = ROOT / "docs/usecases/README.md"
ROW = re.compile(r"^\|\s*(uc-\d+)\s*\|[^|]*\|[^|]*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|")
# Rows the runner has nothing to run for: a page is documentation, draft has no script yet.
NOT_RUN = ("retired", "superseded", "draft", "page")


def runnable(registry: str) -> list[str]:
    """Ids of the registry rows with at least one layer and a status other than the ones above, in id order."""
    ids = []
    for line in registry.splitlines():
        m = ROW.match(line)
        if m and m.group(2) and not any(w in m.group(3).lower().split() for w in NOT_RUN):
            ids.append(m.group(1))
    return sorted(ids, key=lambda s: int(s.split("-")[1]))


def pick(paths: list[str], mapping: dict[str, Any], known: list[str]) -> list[str]:
    chosen = affected_usecases.select(mapping, paths)["chosen"]
    return [uc for uc in known if uc in chosen]


def shard(items: list[str], spec: str) -> list[str]:
    """`I/N`: every Nth item from the Ith (1-based), so slices stay balanced as ids grow."""
    i, _, n = spec.partition("/")
    if not (i.isdigit() and n.isdigit() and 1 <= int(i) <= int(n)):
        raise SystemExit(f"ci_usecases: shard '{spec}' is not I/N with 1 <= I <= N")
    return items[int(i) - 1 :: int(n)]


def classify(results: list[dict[str, Any]], held: set[str]) -> list[dict[str, Any]]:
    for r in results:
        r["status"] = "passed" if r["code"] == 0 else ("quarantined" if quarantine.covers(held, r["id"]) else "failed")
    return results


def report_md(results: list[dict[str, Any]], shards_seen: int, shards_expected: int, run_url: str = "") -> str:
    """The night's record: failures first, one `FAILED` line each, then the quarantined ones and the counts."""
    failed = [r for r in results if r["status"] == "failed"]
    held = [r for r in results if r["status"] == "quarantined"]
    lines = [f"Nightly use cases on develop: {len(results)} ran, {len(failed)} failed, {len(held)} quarantined."]
    if run_url:
        lines.append(f"Run: {run_url}")
    if shards_seen < shards_expected:
        lines.append(f"FAILED shards: only {shards_seen} of {shards_expected} wrote a result file.")
    lines += [f"FAILED {r['id']}  log {r.get('log', '')}" for r in failed]
    lines += [f"quarantined {r['id']}" for r in held]
    return "\n".join(lines)


def git_changed(base: str, head: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return [p for p in out.stdout.splitlines() if p]


def run_ids(ids: list[str], slots: int, timeout: int) -> list[dict[str, Any]]:
    usecase_batch.LOGS.mkdir(parents=True, exist_ok=True)

    def one(item: str) -> dict[str, Any]:
        _, code, waited, ran, log = usecase_batch.run(item, timeout)
        return {"id": item, "code": code, "seconds": round(waited + ran), "log": usecase_batch.shown(log)}

    with ThreadPoolExecutor(max_workers=slots) as pool:
        return list(pool.map(one, ids))


def self_test() -> int:
    registry = (
        "| uc-001 | s | A | api | passing |\n| uc-002 | s | B | api, ui | draft |\n| uc-010 | s | C | ui | failing |\n"
        "| uc-003 | s | D | api | retired |\n| uc-004 | s | E |  | page |\n"
    )
    mapping = {
        "ignore": ["docs/**"],
        "rules": [
            {"row": "kb", "globs": ["services/kb/**"], "usecases": ["uc-001", "uc-002"]},
            {"row": "ui", "globs": ["apps/console/src/app/a/**"], "usecases": ["uc-010"]},
        ],
    }
    known = runnable(registry)
    today = dt.date(2026, 11, 26)
    held = quarantine.active(
        {
            "entries": [
                {"id": "uc-010:ui", "owner": "a", "expires": "2026-12-01"},
                {"id": "uc-1", "owner": "a", "expires": "2026-11-01"},
            ]
        },
        today,
    )
    results = classify(
        [
            {"id": "uc-010:ui", "code": 1},
            {"id": "uc-010:api", "code": 1},
            {"id": "uc-001", "code": 0},
            {"id": "uc-1", "code": 1},
        ],
        held,
    )
    ok = [
        known == ["uc-001", "uc-010"],  # draft, retired and page rows have nothing to run
        pick(["services/kb/x.py"], mapping, known) == ["uc-001"],  # uc-002 is draft, so it is dropped
        pick(["apps/console/src/app/a/page.tsx", "services/kb/y.py"], mapping, known) == ["uc-001", "uc-010"],
        pick(["docs/x.md", "README.md"], mapping, known) == [],  # a docs-only diff runs no use case
        [r["status"] for r in results]
        == ["quarantined", "failed", "passed", "failed"],  # layer-exact; expired gates again
        shard(["a", "b", "c", "d", "e"], "2/3") == ["b", "e"],
        sorted(x for i in (1, 2, 3) for x in shard(list("abcdefg"), f"{i}/3")) == list("abcdefg"),
    ]
    rep = report_md(results, 1, 2)
    ok.append(rep.count("FAILED uc-") == 2 and "quarantined uc-010:ui" in rep and "FAILED shards: only 1 of 2" in rep)
    ok.append("FAILED" not in report_md([{"id": "uc-1", "status": "passed", "log": ""}], 2, 2))
    try:
        shard(["a"], "4/3")
        ok.append(False)
    except SystemExit:
        ok.append(True)
    bad = [i for i, good in enumerate(ok) if not good]
    print("ci_usecases self-test: " + ("ok" if not bad else f"FAILED assertions {bad}"))
    return 0 if all(ok) else 1


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--base", default="origin/develop")
    p.add_argument("--head", default="HEAD")
    a = sub.add_parser("all")
    a.add_argument("--shard", default="1/1")
    r = sub.add_parser("run")
    r.add_argument("--shard", default="1/1")
    r.add_argument("--slots", type=int, default=3)
    r.add_argument("--timeout", type=int, default=900)
    r.add_argument("--out")
    r.add_argument(
        "--no-gate", action="store_true", help="exit 0 whatever failed (the nightly records, it does not gate)"
    )
    r.add_argument("ids", nargs="+")
    n = sub.add_parser("report")
    n.add_argument("dir")
    n.add_argument("--expected", type=int, default=8)
    n.add_argument("--run-url", default="")
    args = ap.parse_args(argv)
    known = runnable(REGISTRY.read_text(encoding="utf-8"))
    if args.cmd == "pick":
        paths = git_changed(args.base, args.head)
        chosen = pick(paths, affected_usecases.load_map(), known)
        print(f"ci_usecases: {len(paths)} files changed, {len(chosen)} use cases", file=sys.stderr)
        print("\n".join(chosen))
        return 0
    if args.cmd == "all":
        print("\n".join(shard(known, args.shard)))
        return 0
    if args.cmd == "report":
        files = sorted(Path(args.dir).glob("**/shard.json"))
        rows = [x for f in files for x in json.loads(f.read_text(encoding="utf-8"))["results"]]
        print(report_md(rows, len(files), args.expected, args.run_url))
        return 0
    ids = shard(args.ids, args.shard)
    held = quarantine.active(quarantine.load(), dt.date.today())
    results = classify(run_ids(ids, args.slots, args.timeout), held)
    for x in results:
        print(f"{x['status'].upper():11} {x['id']:12} {x['seconds']:5}s  {x['log']}")
    failed = [x for x in results if x["status"] == "failed"]
    print(
        f"{sum(x['status'] == 'passed' for x in results)} passed, {len(failed)} failed, "
        f"{sum(x['status'] == 'quarantined' for x in results)} quarantined"
    )
    if args.out:
        Path(args.out).write_text(json.dumps({"results": results}, indent=2) + "\n", encoding="utf-8")
    return 1 if failed and not args.no_gate else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
