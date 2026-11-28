#!/usr/bin/env python3
"""The store tests ci.yml's `store-mssql` job runs on PostgreSQL and SQL Server, kept in scripts/mssql-store-tests.json.

  mssql_store_tests.py units            the job's matrix as JSON: one entry for the shared packages, one per service
  mssql_store_tests.py files <service>  that service's test files, one line (what its matrix entry runs)

scripts/ci-plan.sh prints `units` as `mssql_jobs`; scripts/ci_local.py reads the same file for a local run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DATA = Path(__file__).with_name("mssql-store-tests.json")


def services() -> dict[str, list[str]]:
    return json.loads(DATA.read_text(encoding="utf-8"))["services"]


def units() -> list[dict[str, str]]:
    return [{"unit": "packages"}, *({"unit": s} for s in sorted(services()))]


def main(argv: list[str]) -> int:
    if argv == ["units"]:
        print(json.dumps(units(), separators=(",", ":")))
        return 0
    if len(argv) == 2 and argv[0] == "files" and argv[1] in services():
        print(" ".join(services()[argv[1]]))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
