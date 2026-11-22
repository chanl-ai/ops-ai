#!/usr/bin/env python3
"""`make migration NAME="add case table" [SVC=agents]`: a new Alembic revision whose id starts with the UTC minute,
`20261122_1405_add_case_table`, in the service's chain.

Two builders who each add the next number (0123) on their own branch both pass their own pull request and then clash
at the merge. A timestamp does not repeat across branches, so the files never collide; the chain's single head is
still enforced by scripts/check_migration_heads.py, so two branches that both follow the same revision are refused as
before. Existing revisions keep their ids.

  new_migration.py "<what it changes>" [agents|tools|models|kb|platform|files|documents]
  new_migration.py --self-test
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("agents", "tools", "models", "kb", "platform", "files", "documents")
# Alembic's version table is sized by the first migration of each chain; the longest id in the repo is 55 characters.
MAX_ID = 50


def revision_id(name: str, now: datetime) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not slug:
        raise ValueError("the name has no letters or digits")
    stamp = now.astimezone(UTC).strftime("%Y%m%d_%H%M")
    return f"{stamp}_{slug}"[:MAX_ID].rstrip("_")


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    if not argv or argv[0] == "":
        print('usage: make migration NAME="what it changes" [SVC=agents]')
        return 2
    svc = argv[1] if len(argv) > 1 else "agents"
    if svc not in SERVICES:
        print(f"migration: no service {svc!r}; one of {', '.join(SERVICES)}")
        return 2
    rev = revision_id(argv[0], datetime.now(UTC))
    return subprocess.run(
        ["uv", "run", "alembic", "revision", "-m", argv[0], "--rev-id", rev],
        cwd=ROOT / f"services/{svc}-service",
        check=False,
    ).returncode


def self_test() -> int:
    at = datetime(2026, 11, 22, 14, 5, 59, tzinfo=UTC)
    good = revision_id("Add case table!", at) == "20261122_1405_add_case_table"
    later = revision_id("Add case table!", datetime(2026, 11, 22, 14, 6, tzinfo=UTC)) != revision_id(
        "Add case table!", at
    )
    long = len(revision_id("x" * 90, at)) <= MAX_ID
    try:
        revision_id("!!!", at)
        empty = False
    except ValueError:
        empty = True
    ok = good and later and long and empty
    print("new_migration self-test: " + ("ok" if ok else f"FAILED good={good} later={later} long={long} empty={empty}"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
