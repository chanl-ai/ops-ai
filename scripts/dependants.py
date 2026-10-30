"""The workspace members a change to some packages can break: the packages themselves, then every package and service
that depends on one of them, directly or through another package, read from each member's own pyproject.toml.

scripts/verify-changed.sh runs these instead of the full suite when a commit changes a package (c-566): a package change
used to force a full run whatever it touched. A changed directory that is not a workspace member is printed as
`unknown <dir>`, and the caller then runs everything. --direct stops at the members that list a changed package
themselves: the push check (.githooks/pre-push) runs those, and the full run on each new HEAD covers the rest.

  uv run python scripts/dependants.py [--direct] packages/ops_store packages/ops_policy
  # package packages/ops_store
  # package packages/ops_engine
  # service services/agents-service
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def members(root: Path = ROOT) -> dict[str, tuple[str, list[str]]]:
    """Each workspace member by its distribution name: its directory and the workspace members it depends on."""
    listed = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["uv"]["workspace"]["members"]
    out: dict[str, tuple[str, list[str]]] = {}
    for d in listed:
        project = tomllib.loads((root / d / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        deps = [_name(x) for x in project.get("dependencies", [])]
        out[project["name"]] = (d, deps)
    names = set(out)
    return {n: (d, [x for x in deps if x in names]) for n, (d, deps) in out.items()}


def _name(requirement: str) -> str:
    for stop in "<>=!~[;( ":
        requirement = requirement.split(stop, 1)[0]
    return requirement.strip().lower()


def dependants(changed: list[str], root: Path = ROOT, direct: bool = False) -> tuple[list[str], list[str]]:
    """The member directories `changed` reaches (itself included), and the changed directories that are no member.
    With `direct`, only the changed members and the members that depend on one of them themselves."""
    graph = members(root)
    by_dir = {d: n for n, (d, _) in graph.items()}
    users: dict[str, set[str]] = {n: set() for n in graph}
    for n, (_, deps) in graph.items():
        for dep in deps:
            users[dep].add(n)
    unknown = [c for c in changed if c.rstrip("/") not in by_dir]
    seen: set[str] = set()
    todo = [by_dir[c.rstrip("/")] for c in changed if c.rstrip("/") in by_dir]
    if direct:
        seen = set(todo).union(*(users[n] for n in todo))
        todo = []
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        todo.extend(users[n] - seen)
    return sorted(graph[n][0] for n in seen), unknown


def main(argv: list[str]) -> int:
    reached, unknown = dependants([a for a in argv if a != "--direct"], direct="--direct" in argv)
    for d in reached:
        print(f"{'service' if d.startswith('services/') else 'package'} {d}")
    for d in unknown:
        print(f"unknown {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
