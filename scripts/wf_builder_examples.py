"""Writes the /wf-builder skill's examples page from the seeded workflows (c-535), so the examples the skill adapts are
the ones a dev stack starts with, never a copy that drifted.

    python3 scripts/wf_builder_examples.py           write docs/guide/skills/wf-builder/examples.md
    python3 scripts/wf_builder_examples.py --check   exit 1 when the page is not what the seeds give (make docs-verify)

The standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "services" / "agents-service" / "seed" / "engine_workflows.json"
PAGE = ROOT / "docs" / "guide" / "skills" / "wf-builder" / "examples.md"


def render(seeds: Path) -> str:
    """The page: each seeded workflow's id, name and purpose, its steps by type, and every way out of each step."""
    items = cast(list[dict[str, Any]], json.loads(seeds.read_text()))
    out = [
        "# /wf-builder examples",
        "",
        "Status: current. Generated from `services/agents-service/seed/engine_workflows.json` by",
        "`scripts/wf_builder_examples.py`; change the seeds, then run it. `make docs-verify` fails on a stale page.",
        "",
        "Each example is a seeded workflow a dev stack starts with. Name one as `example` in a goal file and",
        "`scripts/wf_builder.py create` adapts it.",
    ]
    for item in items:
        nodes = {str(n["id"]): n for n in item.get("nodes") or []}
        about = f"{item.get('name') or item['id']}. {item.get('description') or ''}".strip()
        out += ["", f"## {item['id']}", "", about]
        out += ["", "| Step | Type |", "|---|---|"]
        out += [f"| {n.get('name') or i} (`{i}`) | `{n['type']}` |" for i, n in nodes.items()]
        out += ["", "| From | Port | To |", "|---|---|---|"]
        for c in item.get("connections") or []:
            src, dst = c["from"], c["to"]
            out.append(f"| `{src['node']}` | {src['port']} | `{dst['node']}` |")
    return "\n".join(out) + "\n"


def check(seeds: Path, page: Path) -> list[str]:
    """What is wrong with the page: missing, or not what the seeds give."""
    if not page.is_file():
        return [f"{page} is missing; run python3 scripts/wf_builder_examples.py"]
    if page.read_text() != render(seeds):
        return [f"{page} does not match the seeds; run python3 scripts/wf_builder_examples.py"]
    return []


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="wf_builder_examples.py", description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    if args.check:
        problems = check(SEEDS, PAGE)
        for problem in problems:
            print(f"wf-builder examples: {problem}", file=sys.stderr)
        return 1 if problems else 0
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(render(SEEDS))
    print(f"wrote {PAGE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
