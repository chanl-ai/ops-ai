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
import contextlib
import datetime as dt
import io
import json
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
ROW = re.compile(r"^\|\s*(uc-[a-z0-9]+(?:-[a-z0-9]+)*)\s*\|[^|]*\|[^|]*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|")
# Rows the runner has nothing to run for: a page is documentation, draft has no script yet.
NOT_RUN = ("retired", "superseded", "draft", "page")


def runnable(registry: str) -> list[str]:
    """Ids of the registry rows with at least one layer and a status other than the ones above, in id order."""
    ids = []
    for line in registry.splitlines():
        m = ROW.match(line)
        if m and m.group(2) and not any(w in m.group(3).lower().split() for w in NOT_RUN):
            ids.append(m.group(1))
    # Numbered ids first in number order, then the named ones (uc-workflows-1) in name order.
    return sorted(ids, key=lambda s: (0, int(s.split("-")[1]), "") if s.split("-")[1].isdigit() else (1, 0, s))


# Use cases one pull request run may pick: 45 minutes on three slots fits about this many; a wider pick (a diff that
# touches shared code) is left to the nightly, which runs every one.
MAX_PICK = 40


def cap(chosen: list[str], limit: int = MAX_PICK) -> tuple[list[str], str]:
    """The pick, or nothing with the reason when it is larger than one run can finish."""
    if len(chosen) <= limit:
        return chosen, ""
    return (
        [],
        f"{len(chosen)} use cases affected, more than the {limit} one run fits: "
        "left to the nightly (nightly-usecases.yml)",
    )


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


def write_results(path: str | None, results: list[dict[str, Any]]) -> None:
    if path:
        Path(path).write_text(json.dumps({"results": results}, indent=2) + "\n", encoding="utf-8")


def run_ids(
    ids: list[str], slots: int, timeout: int, *, held: set[str], out: str | None = None
) -> list[dict[str, Any]]:
    """Runs the ids and rewrites the result file after each one finishes, so a run cut off by the job's time limit
    still leaves every result so far."""
    usecase_batch.LOGS.mkdir(parents=True, exist_ok=True)

    def one(item: str) -> dict[str, Any]:
        _, code, waited, ran, log = usecase_batch.run(item, timeout)
        return {"id": item, "code": code, "seconds": round(waited + ran), "log": usecase_batch.shown(log)}

    done: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=slots) as pool:
        for fut in as_completed([pool.submit(one, i) for i in ids]):
            done.append(fut.result())
            classify([done[-1]], held)
            print(
                f"{done[-1]['status'].upper():13} {done[-1]['id']:12} {done[-1]['seconds']:5}s  {done[-1]['log']}",
                flush=True,
            )
            write_results(out, done)
    return done


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
    named = runnable("| uc-workflows-2 | s | A | api | passing |\n| uc-007 | s | B | ui | failing |\n")
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
        named == ["uc-007", "uc-workflows-2"],  # a named id runs too, after the numbered ones
        cap(["uc-1", "uc-2", "uc-3"], 5) == (["uc-1", "uc-2", "uc-3"], ""),
        cap(["uc-1", "uc-2", "uc-3"], 2)[0] == [] and "nightly" in cap(["uc-1", "uc-2", "uc-3"], 2)[1],
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
    with tempfile.TemporaryDirectory() as tmp:
        seen: list[int] = []
        real_run, real_logs = usecase_batch.run, usecase_batch.LOGS
        out = Path(tmp) / "r.json"

        def fake(item: str, timeout: int) -> tuple[str, int, float, float, Path]:
            # uc-2 waits (at most 5 s) for uc-1's result to reach the file while the run is still going.
            if item == "uc-2":
                for _ in range(100):
                    if out.exists() and json.loads(out.read_text())["results"]:
                        seen.append(1)
                        break
                    time.sleep(0.05)
            return item, 0, 0.0, 0.0, Path(tmp) / "x.log"

        usecase_batch.run, usecase_batch.LOGS = fake, Path(tmp)  # type: ignore[assignment]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    ["run", "--slots", "1", "--out", str(out), "uc-1", "uc-2"]
                )  # the real entry, arguments and all
        except TypeError:
            code = -1
        finally:
            usecase_batch.run, usecase_batch.LOGS = real_run, real_logs
        ok.append(code == 0 and seen == [1] and len(json.loads(out.read_text())["results"]) == 2)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "none.json"
        real_changed = globals()["git_changed"]
        globals()["git_changed"] = lambda base, head: ["docs/x.md"]  # a diff that affects no use case
        buf, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                pick_code = main(["pick"])
                picked = buf.getvalue()
                run_code = main(["run", "--out", str(out)])  # no ids: what CI passes when the pick is empty
        except SystemExit as e:  # argparse refusing the empty list
            pick_code = run_code = int(e.code or 0)
        finally:
            globals()["git_changed"] = real_changed
        # An empty pick prints nothing: a blank line becomes the output " ", which is not empty to the workflow's `if`.
        ok.append(picked == "" and pick_code == 0 and run_code == 0)
        ok.append(out.exists() and json.loads(out.read_text())["results"] == [])
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
    r.add_argument("ids", nargs="*")
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
        chosen, why = cap(chosen)
        if why:
            print(f"ci_usecases: {why}", file=sys.stderr)
        if chosen:
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
    if not ids:
        print("ci_usecases: no use cases to run")
        write_results(args.out, [])
        return 0
    held = quarantine.active(quarantine.load(), dt.date.today())
    results = run_ids(ids, args.slots, args.timeout, held=held, out=args.out)
    failed = [x for x in results if x["status"] == "failed"]
    print(
        f"{sum(x['status'] == 'passed' for x in results)} passed, {len(failed)} failed, "
        f"{sum(x['status'] == 'quarantined' for x in results)} quarantined"
    )
    return 1 if failed and not args.no_gate else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
