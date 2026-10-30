"""uc-565 a SQL Server install migrates agents to the head, api layer:
docs/usecases/agents-service/a-sql-server-install-migrates-agents.md. A DBA's two paths, each on its own scratch
database: the HEAD bundle on an empty database, and an earlier release's bundle upgraded with the upgrade SQL to
HEAD. Each ends compared with the store models. Runs where sqlcmd is (the test image) against OPS_MSSQL_SERVER with
MSSQL_SA_PASSWORD; `make uc-sql-server` builds the folders it reads and runs it beside the SQL Server test machine.
Without the two upgrade folders it runs the fresh install only: upgrades start from the first release whose bundle
installs, and until a migration lands after that release there is nothing to upgrade.

    python test-uc-565-api.py <head bundle> [<earlier release's bundle> <upgrade folder>]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "deploy" / "database"))
from mssql_live import drift, drop, engine, install, sqlcmd
from usecase_harness import check, finish

# The checkpointer's tables: a chat turn saves its state in them.
CHECKPOINTER = ("ops_checkpoints", "ops_checkpoint_writes", "ops_checkpoint_fences")


def state(database: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """What the database holds: its tables, each chain's version row, and the memory full-text index."""
    eng = engine(database)
    try:
        with eng.connect() as c:
            tables = set(sa.inspect(c).get_table_names(schema="dbo"))
            versions = {
                ch["name"]: c.execute(sa.text(f"SELECT version_num FROM {ch['versionTable']}")).scalar()
                for ch in manifest["chains"]
            }
            fts = c.execute(sa.text("SELECT CAST(FULLTEXTSERVICEPROPERTY('IsFullTextInstalled') AS int)")).scalar()
            indexed = c.execute(
                sa.text("SELECT COUNT(*) FROM sys.fulltext_indexes WHERE object_id = OBJECT_ID('agent_memories')")
            ).scalar()
    finally:
        eng.dispose()
    return {"tables": tables, "versions": versions, "full_text": not fts or bool(indexed)}


def at_head(step: str, database: str, manifest: dict[str, Any]) -> None:
    held = state(database, manifest)
    heads = {ch["name"]: ch["head"] for ch in manifest["chains"]}
    check(f"{step} every chain's version row is its head", held["versions"] == heads, held["versions"])
    missing = [t for t in CHECKPOINTER if t not in held["tables"]]
    check(f"{step} the checkpointer's tables are there", not missing, missing)
    check(f"{step} memory search has its full-text index", held["full_text"])
    found = drift(database)
    check(f"{step} no drift from the store models and their tenant policies", not found, found[:20])


def main(head: Path, base: Path | None = None, upgrade: Path | None = None) -> None:
    manifest = json.loads((head / "manifest.json").read_text())
    # Logins are server-wide and each install makes the same ones, so the two paths run one after the other.
    fresh = f"ops_uc565_{uuid4().hex[:8]}"
    try:
        install(head, fresh)
        check("1 the HEAD bundle installs on an empty database", True)
        at_head("2", fresh, manifest)
    except SystemExit as e:
        check("1 the HEAD bundle installs on an empty database", False, str(e)[-1500:])
    finally:
        drop(fresh)

    if base is None or upgrade is None:
        print("WAIT 3-5 the upgrade: no earlier SQL Server release whose bundle installs", flush=True)
        return
    upgraded = f"ops_uc565_{uuid4().hex[:8]}"
    try:
        install(base, upgraded)
        check("3 the earlier release's bundle installs", True)
        sqlcmd(upgraded, upgrade / "upgrade.sql")
        sqlcmd(upgraded, head / "grants.sql")
        check("4 the upgrade SQL takes it to HEAD", True)
        at_head("5", upgraded, manifest)
    except SystemExit as e:
        check("4 the upgrade SQL takes it to HEAD", False, str(e)[-1500:])
    finally:
        drop(upgraded)


main(*(Path(p) for p in sys.argv[1:4]))
finish()
