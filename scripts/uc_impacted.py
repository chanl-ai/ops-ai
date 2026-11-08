#!/usr/bin/env python3
"""The UI use cases a change should run: the core list (config/ui-core-usecases.txt) plus the ones the changed paths
reach through config/ui-impact-map.txt.

    python3 scripts/uc_impacted.py [--base origin/main] [--max N] [--ids] [--explain]
    python3 scripts/uc_impacted.py --summary <outdir> [--verbose]

Prints each selected use case with its reason (core, or the changed path that picked it), the impacted ones left out
past --max, and every changed path no area of the map names, so the map can be filled in. --ids prints only the
selected ids, one line, for the make target to run. --summary reads a finished run's results (scripts/uc_shard.py
writes them): one line per use case, and for a failure the first failing check, its error in at most three lines and a
screenshot path; --verbose adds every full log. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "config/ui-core-usecases.txt"
MAP = ROOT / "config/ui-impact-map.txt"
# Impacted use cases beyond the core list, the ones the most changed paths reach first: each takes two to three
# minutes, so an unbounded list would turn a wide change back into the full pass.
MAX_IMPACTED = 8


@dataclass(frozen=True)
class Area:
    name: str
    globs: tuple[re.Pattern[str], ...]
    ucs: tuple[str, ...]


@dataclass
class Selection:
    # Selected ids in run order, each with why it was picked.
    reasons: dict[str, str] = field(default_factory=dict[str, str])
    # Impacted ids past the cap, with the number of changed paths that reached each.
    left_out: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])
    unmapped: list[str] = field(default_factory=list[str])


def glob_re(glob: str) -> re.Pattern[str]:
    """A path glob as a regex: `**/` any directories (none included), `**` anything, `*` and `?` within one name."""
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif glob.startswith("**", i):
            out, i = out + ".*", i + 2
        elif glob[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif glob[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(glob[i]), i + 1
    return re.compile(out + r"\Z")


def read_core(text: str) -> list[str]:
    return [line.split()[0] for line in text.splitlines() if line.strip() and not line.startswith("#")]


def read_map(text: str) -> list[Area]:
    areas: list[Area] = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, globs, ucs = (part.strip() for part in line.split("|"))
        areas.append(
            Area(
                name,
                tuple(glob_re(g.strip()) for g in globs.split(",") if g.strip()),
                tuple(u for u in ucs.split() if u != "-"),
            )
        )
    return areas


def select(changed: list[str], core: list[str], areas: list[Area], max_impacted: int = MAX_IMPACTED) -> Selection:
    sel = Selection()
    for uc in core:
        sel.reasons[uc] = "core"
    hits: dict[str, list[str]] = {}
    for path in changed:
        matched = [a for a in areas if any(g.match(path) for g in a.globs)]
        if any(not a.ucs for a in matched):
            # A doc, test or tooling path changes no UI behaviour, whatever folder it sits in.
            continue
        if not matched:
            sel.unmapped.append(path)
        for a in matched:
            for uc in a.ucs:
                hits.setdefault(uc, []).append(path)
    ranked = sorted((uc for uc in hits if uc not in sel.reasons), key=lambda uc: (-len(hits[uc]), uc))
    for uc in ranked[:max_impacted]:
        more = len(hits[uc]) - 1
        sel.reasons[uc] = f"changed {hits[uc][0]}" + (f" and {more} more" if more else "")
    sel.left_out = [(uc, len(hits[uc])) for uc in ranked[max_impacted:]]
    return sel


def changed_since(base: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return [p for p in out.stdout.splitlines() if p]


RUNNER_LINE = re.compile(r"FAIL +uc-\d+ +\w+ +script exited")
TIME = re.compile(r"^TIME (\S+) ([\d.]+)$")


def first_failure(log: str) -> list[str]:
    """The first FAIL line, cut to 240 characters, and up to two lines after it that are not other check results."""
    lines = log.splitlines()
    for i, line in enumerate(lines):
        # The runner's "FAIL uc-NNN ui  script exited" line is a consequence of the check line.
        if line.startswith("FAIL ") and not RUNNER_LINE.match(line):
            tail = [
                x
                for x in lines[i + 1 : i + 6]
                if x.strip()
                and not x.startswith(("PASS ", "FAIL ", "TIME ", "node:"))
                and "triggerUncaughtException" not in x
                and x.strip() != "^"
            ][:2]
            return [x[:240] for x in [line, *tail]]
    # No check failed: the script threw before the next check. Node prints the message under a caret line.
    for i, line in enumerate(lines):
        if line.strip() == "^":
            return [x[:240] for x in [y for y in lines[i + 1 :] if y.strip()][:3]]
    quiet = [x for x in lines if x.strip() and not x.startswith(("PASS ", "TIME ", "FAIL "))]
    return [x[:240] for x in quiet[-3:]]


def summarize(out: Path, verbose: bool) -> int:
    rows = [line.split("\t") for f in sorted(out.glob("results.*.tsv")) for line in f.read_text().splitlines()]
    rows.sort(key=lambda r: r[1])
    failed = 0
    for status, uc, secs in rows:
        log = out / f"{uc}.log"
        text = log.read_text(errors="replace") if log.exists() else ""
        times = {m[1]: float(m[2]) for m in map(TIME.match, text.splitlines()) if m}
        phases = " ".join(f"{k} {times[k]:.0f}s" for k in ("stack-ready", "body") if k in times)
        print(f"{status} {uc} {secs}s  {phases}".rstrip())
        if status != "PASS":
            failed += 1
            for x in first_failure(text):
                print(f"    {x}")
            pngs = (out / "evidence").glob(f"{uc.removeprefix('uc-')}/**/*.png")
            shots = sorted(pngs, key=lambda p: p.stat().st_mtime)
            print(f"    screenshot: {shots[-1] if shots else 'none'}  log: {log}")
        if verbose:
            print(text)
    seen = {uc: int(secs) for _, uc, secs in rows}
    try:
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ops-ai" / "uc-seconds.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        old = json.loads(cache.read_text()) if cache.exists() else {}
        cache.write_text(json.dumps({**old, **seen}))
    except (OSError, ValueError):
        pass  # only the claim order depends on it
    print(f"{len(rows) - failed}/{len(rows)} passed; logs in {out} (VERBOSE=1 prints them)")
    return 1 if failed or not rows else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--max", type=int, default=MAX_IMPACTED)
    ap.add_argument("--ids", action="store_true")
    ap.add_argument("--explain", action="store_true")
    ap.add_argument("--summary", type=Path)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    if args.summary:
        return summarize(args.summary, args.verbose)
    sel = select(changed_since(args.base), read_core(CORE.read_text()), read_map(MAP.read_text()), args.max)
    if args.ids:
        print(" ".join(sel.reasons))
        return 0
    core = sum(why == "core" for why in sel.reasons.values())
    print(
        f"ui use cases since {args.base}: {len(sel.reasons)} ({core} core, {len(sel.reasons) - core} impacted); "
        f"{len(sel.left_out)} left out past --max {args.max}, {len(sel.unmapped)} changed paths unmapped "
        "(--explain lists them)"
    )
    if args.explain:
        for uc, why in sel.reasons.items():
            print(f"  {uc}  {why}")
        if sel.left_out:
            print("left out: " + ", ".join(f"{uc} ({n} paths)" for uc, n in sel.left_out))
        if sel.unmapped:
            print(f"unmapped paths, add them to {MAP.relative_to(ROOT)}:")
            for p in sel.unmapped:
                print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
