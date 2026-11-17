"""Writes the "Breaking changes" block of docs/sdk/changelog-next-major.md from
docs/architecture/migration/api-changes.md.

    uv run python sdk/changelog_from_api_changes.py           rewrite the block
    uv run python sdk/changelog_from_api_changes.py --check   exit 1 when the block is out of date

A row of api-changes.md is breaking when its "Old form works" cell is not "Yes". One line per row, grouped by service:
route, what changed, what a caller must do.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "architecture" / "migration" / "api-changes.md"
TARGET = ROOT / "docs" / "sdk" / "changelog-next-major.md"
START, END = "<!-- breaking:start (sdk/changelog_from_api_changes.py) -->", "<!-- breaking:end -->"


def cells(row: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]


def block() -> str:
    service, groups = "", {}
    for line in SOURCE.read_text().splitlines():
        if line.startswith(("## ", "### ")):
            name = line.lstrip("# ").strip()
            if name.endswith("service") or name == "every service":
                service = name
            continue
        if not line.startswith("|") or line.startswith("|---") or not service:
            continue
        c = cells(line)
        if len(c) != 6 or c[0] == "Route" or c[5].lower() == "yes":
            continue
        route, what, _before, _after, must, works = c
        groups.setdefault(service, []).append(
            f"- {route}: {what}. {must.rstrip('.')}. Old form works: {works.lower()}."
        )
    out = ["## Breaking changes", ""]
    for name, lines in groups.items():
        out += [f"### {name}", "", *lines, ""]
    return "\n".join(out).rstrip() + "\n"


def render(text: str) -> str:
    new = f"{START}\n{block()}{END}"
    if START in text:
        return re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: new, text, flags=re.S)
    head, _, rest = text.partition("\n\n")
    return f"{head}\n\n{new}\n\n{rest}"


def main() -> int:
    text = TARGET.read_text()
    new = render(text)
    if "--check" in sys.argv:
        return 0 if new == text else 1
    TARGET.write_text(new)
    sys.stdout.write(f"{sum(1 for line in new.splitlines() if line.startswith('- '))} breaking lines\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
