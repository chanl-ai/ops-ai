"""List the use cases to run for the files changed between two commits.

Usage: python scripts/agents/affected_usecases.py <base> [<head>]
       python scripts/agents/affected_usecases.py --self-test

Each changed file is matched against the globs in `usecase_map.json` (next to this script); a changed use case
script (`docs/usecases/<service>/scripts/test-uc-NNN-<layer>.*`) selects its own use case. The output lists every
selected use case with the layers the registry (`docs/usecases/README.md` at <head>, else origin/main) gives it,
then the changed files that match no glob as "uncovered": each one is a page or module the coverage plan has no row
for yet. Files on the map's ignore list (docs, tests, lock files) are counted but not listed. Exit code 0 always;
the caller decides what an uncovered file means for a release.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from review_context import matches

MAP_FILE = Path(__file__).resolve().parent / "usecase_map.json"
REGISTRY = "docs/usecases/README.md"
OWN_SCRIPT = re.compile(r"^docs/usecases/.+/scripts/test-(uc-\d+)-[a-z]+\.[a-z]+$")
REGISTRY_ROW = re.compile(r"^\|\s*(uc-\d+)\s*\|[^|]*\|[^|]*\|\s*([^|]+?)\s*\|")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def registry_layers(text: str) -> dict[str, list[str]]:
    layers: dict[str, list[str]] = {}
    for line in text.splitlines():
        m = REGISTRY_ROW.match(line)
        if m:
            layers[m.group(1)] = [part.strip() for part in m.group(2).split(",") if part.strip()]
    return layers


def registry_at(head: str) -> dict[str, list[str]]:
    """The registry as of <head>, filled in from origin/main for use cases added after <head>.

    <head> wins so a release reads the layers it ships; the map is built from the newest plan, so an older range can
    name a use case its own registry does not have yet, and origin/main still knows its layers.
    """
    layers: dict[str, list[str]] = {}
    for rev in ("origin/main", head):
        try:
            layers.update(registry_layers(git("show", f"{rev}:{REGISTRY}")))
        except subprocess.CalledProcessError:
            continue
    return layers


def select(mapping: dict, paths: list[str]) -> dict[str, object]:
    """Use case id -> the rows and files that chose it, plus the uncovered and ignored files."""
    chosen: dict[str, dict[str, set[str]]] = {}
    uncovered: list[str] = []
    gaps: dict[str, list[str]] = {}
    ignored = 0
    for path in paths:
        own = OWN_SCRIPT.match(path)
        if own:
            entry = chosen.setdefault(own.group(1), {"rows": set(), "files": set()})
            entry["rows"].add("its own script")
            entry["files"].add(path)
            continue
        if any(matches(path, g) for g in mapping.get("ignore", [])):
            ignored += 1
            continue
        hit = False
        for rule in mapping["rules"]:
            if not any(matches(path, g) for g in rule["globs"]):
                continue
            hit = True
            if not rule["usecases"]:
                gaps.setdefault(rule["row"], []).append(path)
            for uc in rule["usecases"]:
                entry = chosen.setdefault(uc, {"rows": set(), "files": set()})
                entry["rows"].add(rule["row"])
                entry["files"].add(path)
        if not hit:
            uncovered.append(path)
    return {"chosen": chosen, "uncovered": uncovered, "gaps": gaps, "ignored": ignored}


def report(result: dict, layers: dict[str, list[str]], base: str, head: str, changed: int) -> str:
    chosen = result["chosen"]
    lines = [f"{changed} files changed in {base}..{head}; {len(chosen)} use cases cover them"]
    for uc in sorted(chosen, key=lambda s: int(s.split("-")[1])):
        lay = ",".join(layers.get(uc, [])) or "not in registry"
        rows = "; ".join(sorted(chosen[uc]["rows"]))
        lines.append(f"  {uc} [{lay}]  {rows}")
    for row, files in result["gaps"].items():
        lines.append(f"no use case yet for row '{row}': {', '.join(files)}")
    lines.append(f"uncovered: {len(result['uncovered'])}")
    lines.extend(f"  {p}" for p in result["uncovered"])
    lines.append(f"ignored (docs, tests, lock files): {result['ignored']}")
    return "\n".join(lines)


FIXTURE_MAP = {
    "ignore": ["docs/**", "**/tests/**"],
    "rules": [
        {"row": "Knowledge bases", "globs": ["apps/console/src/app/knowledge/**"], "usecases": ["uc-096", "uc-129"]},
        {"row": "Agent page", "globs": ["apps/console/src/app/agents/[id]/**"], "usecases": ["uc-018"]},
        {"row": "Triggers: schedules", "globs": ["services/a/timers.py"], "usecases": []},
    ],
}
FIXTURE_REGISTRY = (
    "| Id | Service | Title | Layers | Status |\n"
    "| uc-096 | console | KB | ui | passing |\n"
    "| uc-129 | kb | Add | api, ui | x |\n"
)


def self_test() -> bool:
    """Each case is a way the selector could pick the wrong use cases or hide a gap."""
    paths = [
        "apps/console/src/app/knowledge/[id]/page.tsx",
        "apps/console/src/app/agents/[id]/page.tsx",
        "apps/console/src/app/wiki/page.tsx",
        "docs/usecases/kb-service/scripts/test-uc-677-api.py",
        "docs/plans/x.md",
        "apps/console/src/app/knowledge/tests/x.test.ts",
        "services/a/timers.py",
    ]
    r = select(FIXTURE_MAP, paths)
    layers = registry_layers(FIXTURE_REGISTRY)
    cases = [
        ("a mapped page selects every use case on its row", {"uc-096", "uc-129"} <= set(r["chosen"])),
        ("a bracketed route folder matches literally", "uc-018" in r["chosen"]),
        ("an unmapped page is reported as uncovered", r["uncovered"] == ["apps/console/src/app/wiki/page.tsx"]),
        ("a changed use case script selects its own id", "uc-677" in r["chosen"]),
        ("docs and tests are ignored, not uncovered", r["ignored"] == 2),
        ("a row with no use case is named as a gap", r["gaps"] == {"Triggers: schedules": ["services/a/timers.py"]}),
        ("layers come from the registry row", layers == {"uc-096": ["ui"], "uc-129": ["api", "ui"]}),
        ("the shipped map parses and every rule has globs", all(rule["globs"] for rule in load_map()["rules"])),
    ]
    for name, ok in cases:
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    return all(ok for _, ok in cases)


def load_map() -> dict:
    return json.loads(MAP_FILE.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base", nargs="?", help="the commit the change is measured from")
    parser.add_argument("head", nargs="?", default="HEAD", help="the commit the change ends at (default HEAD)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return 0 if self_test() else 1
    if not args.base:
        parser.error("name the base commit")
    paths = [p for p in git("diff", "--name-only", f"{args.base}..{args.head}").splitlines() if p]
    result = select(load_map(), paths)
    layers = registry_at(args.head)
    if args.json:
        out = {
            "usecases": {uc: layers.get(uc, []) for uc in sorted(result["chosen"])},
            "uncovered": result["uncovered"],
            "gaps": result["gaps"],
        }
        print(json.dumps(out, indent=1))
    else:
        print(report(result, layers, args.base, args.head, len(paths)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
