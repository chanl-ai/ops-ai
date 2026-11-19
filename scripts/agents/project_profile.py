"""Read the project profile the agent scripts take their facts from.

The profile is a markdown file (`.claude/project-profile.md`, or the file `OPS_AGENT_PROFILE` names) whose tables
are the only place a script learns the repository's layout: which paths form a layer, where tests live, which
checks run first, which people a browser walk signs in as. A script asks for a section's table by its heading and
reads cells by column name, so another repository changes the profile, not the scripts.

  python3 scripts/agents/project_profile.py                 every table, as JSON
  python3 scripts/agents/project_profile.py --section Tests  one section's tables
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

PROFILE_PATH = ".claude/project-profile.md"
_SEPARATOR = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def find_root(start: Path | None = None) -> Path:
    """The repository root: git's answer, else the first parent holding the profile, else the current folder."""
    start = (start or Path.cwd()).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True, check=True
        ).stdout.strip()
        if out:
            return Path(out)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    for folder in (start, *start.parents):
        if (folder / PROFILE_PATH).is_file():
            return folder
    return start


def plain(cell: str) -> str:
    """A cell's text without the backticks that mark code in the markdown."""
    return cell.replace("`", "").strip()


def cells(line: str) -> list[str]:
    """The cells of one table row; a `\\|` inside a cell stays a bar."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    parts = re.split(r"(?<!\\)\|", body)
    return [p.replace("\\|", "|").strip() for p in parts]


@dataclass
class Profile:
    """The profile's tables, grouped by the heading they sit under."""

    path: Path
    root: Path
    sections: dict[str, list[list[dict[str, str]]]] = field(default_factory=dict)

    def tables(self, section: str) -> list[list[dict[str, str]]]:
        """Every table under the heading `section` (matched without case); an unknown heading is an error."""
        for name, tables in self.sections.items():
            if name.lower() == section.lower():
                return tables
        raise KeyError(f"profile {self.path} has no section {section!r}; it has {sorted(self.sections)}")

    def table(self, section: str, column: str | None = None) -> list[dict[str, str]]:
        """The first table under `section`, or the first one whose columns include `column`."""
        tables = self.tables(section)
        if column is None:
            return tables[0] if tables else []
        for rows in tables:
            if rows and column in rows[0]:
                return rows
        raise KeyError(f"profile section {section!r} has no table with a column {column!r}")

    def value(self, section: str, key: str, key_column: str = "Setting", value_column: str = "Value") -> str:
        """One setting from a key/value table, without backticks."""
        for row in self.table(section, key_column):
            if plain(row.get(key_column, "")).lower() == key.lower():
                return plain(row.get(value_column, ""))
        raise KeyError(f"profile section {section!r} has no row {key!r}")


def parse(text: str, path: Path, root: Path) -> Profile:
    """Every markdown table in `text`, keyed by the nearest heading above it."""
    profile = Profile(path=path, root=root)
    section = ""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#"):
            section = line.lstrip("#").strip()
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and _SEPARATOR.match(lines[i + 1].strip()):
            header = cells(line)
            rows: list[dict[str, str]] = []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                values = cells(lines[i])
                rows.append({header[j]: (values[j] if j < len(values) else "") for j in range(len(header))})
                i += 1
            profile.sections.setdefault(section, []).append(rows)
            continue
        i += 1
    return profile


def load(path: str | os.PathLike[str] | None = None, root: Path | None = None) -> Profile:
    """The profile at `path`, else `OPS_AGENT_PROFILE`, else the repository's own."""
    root = root or find_root()
    chosen = Path(path or os.environ.get("OPS_AGENT_PROFILE") or root / PROFILE_PATH)
    if not chosen.is_absolute():
        chosen = root / chosen
    if not chosen.is_file():
        sys.exit(f"no project profile at {chosen}; write one (see .claude/project-profile.md) or set OPS_AGENT_PROFILE")
    return parse(chosen.read_text(encoding="utf-8"), chosen, root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", help="the profile file (default: OPS_AGENT_PROFILE or .claude/project-profile.md)")
    parser.add_argument("--section", help="print only this section's tables")
    args = parser.parse_args(argv)
    profile = load(args.profile)
    out = {args.section: profile.tables(args.section)} if args.section else profile.sections
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
