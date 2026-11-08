#!/usr/bin/env python3
"""The UI use cases a change should run: the core list (config/ui-core-usecases.txt) plus the ones the changed paths
reach through config/ui-impact-map.txt.

    python3 scripts/uc_impacted.py [--base origin/main] [--max N] [--ids]

Prints each selected use case with its reason (core, or the changed path that picked it), the impacted ones left out
past --max, and every changed path no area of the map names, so the map can be filled in. --ids prints only the
selected ids, one line, for the make target to run. Stdlib only.
"""

from __future__ import annotations

import argparse
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--max", type=int, default=MAX_IMPACTED)
    ap.add_argument("--ids", action="store_true")
    args = ap.parse_args()
    sel = select(changed_since(args.base), read_core(CORE.read_text()), read_map(MAP.read_text()), args.max)
    if args.ids:
        print(" ".join(sel.reasons))
        return 0
    print(f"ui use cases for the change since {args.base}: {len(sel.reasons)}")
    for uc, why in sel.reasons.items():
        print(f"  {uc}  {why}")
    if sel.left_out:
        print(f"left out past --max {args.max}: " + ", ".join(f"{uc} ({n} paths)" for uc, n in sel.left_out))
    if sel.unmapped:
        print(f"unmapped paths ({len(sel.unmapped)}), add them to {MAP.relative_to(ROOT)}:")
        for p in sel.unmapped:
            print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
