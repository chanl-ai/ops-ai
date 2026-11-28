"""Refuse a migration that fills rows with row security switched off.

A deployment's migrator owns the tables but is no superuser and has no BYPASSRLS. With FORCE ROW LEVEL SECURITY on a
table, PostgreSQL refuses that owner's statement outright when `row_security` is off ("query would be affected by
row-level security policy"), so such a fill stops an upgrade half way; on SQL Server the policy hides every row from
the migrator instead. A migration that reads or writes every tenant's rows sets the policies aside with
`ops_store.schema.backfill_ddl`. The revisions that held the setting before this check are older than the offline
upgrade floor and every supported install has run them; they are in scripts/row-security-off-waiting.txt, which only
shrinks.

  python3 scripts/check_owner_fills.py [--root <tree>] [--waiting <file>]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROW_SECURITY_OFF = re.compile(
    r"row_security\s*(=|\bto\b)\s*'?off|set_config\(\s*'row_security'\s*,\s*'off'", re.IGNORECASE
)


def check(root: Path, waiting_file: Path) -> int:
    listed = {line.strip() for line in waiting_file.read_text().splitlines() if line.strip()}
    found = {
        str(p.relative_to(root))
        for top in ("services", "packages")
        for p in (root / top).glob("*/migrations/versions/*.py")
        if ROW_SECURITY_OFF.search(p.read_text())
    }
    for path in sorted(found - listed):
        print(f"check-owner-fills: {path}: switches row_security off; set the policies aside with backfill_ddl")
    for path in sorted(listed - found):
        print(f"check-owner-fills: {path}: no longer switches row_security off; remove it from {waiting_file.name}")
    return 1 if found != listed else 0


def main(argv: list[str]) -> int:
    root = Path(argv[argv.index("--root") + 1]) if "--root" in argv else Path(".")
    waiting = (
        Path(argv[argv.index("--waiting") + 1]) if "--waiting" in argv else Path("scripts/row-security-off-waiting.txt")
    )
    return check(root, waiting if waiting.is_absolute() else root / waiting)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
