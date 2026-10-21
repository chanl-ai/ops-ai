"""Ops AI's schema as reviewed scripts for a DBA, generated from the Alembic chains (runbook docs/deploy/database.md).

    uv run python deploy/database/schema.py ddl --server <url> --out <dir> [--ref <git ref>]
        the baseline: roles.sql, one file per service, bundle.sql, grants.sql, manifest.json, SHA256SUMS
    uv run python deploy/database/schema.py upgrade-sql --from <ref> --to <ref> --out <dir>
        upgrade.sql and downgrade.sql: one guarded, checksummed step per revision, in migrate order
    uv run python deploy/database/schema.py drift --database <url> --server <url> [--ref <git ref>]
        every difference between a live database and the schema its version rows describe; exit 1 on any
    uv run python deploy/database/schema.py diff <url> <url>
        every difference between two databases' schemas; exit 1 on any

`--server` is a server where the tool may create and drop scratch databases (and where the chains' roles may be
created): a throwaway one, never production. Every ref is exported with `git archive`, so uncommitted files never
reach a script; `--ref .` takes this folder as it is (inside an export). The migrations stay the source: the baseline
is a dump of a scratch database the chains just migrated (eight applied revisions read rows or inspect tables and
cannot render offline), split by which chain created each object; an upgrade is Alembic's offline SQL, one revision
at a time. A service's runtime role gets DML on the tables its chain creates and the ones its code declares.
Dialect-specific steps live in the dialect (postgres.py); `--dialect` picks it.
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
from postgres import Dump, Entry, Postgres, render

ROOT = Path(__file__).resolve().parents[2]
MIGRATE = ROOT / "deploy" / "images" / "migrate.sh"
CHAINS = ROOT / "deploy" / "images" / "chains"
# DIALECT=mssql compiles the schema from the store models with no server, and main() hands it to mssql.py.
DIALECTS: dict[str, Any] = {"postgresql": Postgres, "mssql": None}
MIGRATOR = "ops_migrator"
# Revisions applied before offline rendering was a rule: they read rows or inspect tables, so Alembic cannot render them
# as SQL. Every later revision must render (test_offline.py); an upgrade across one of these is refused by name.
ONLINE_ONLY = {
    "agents": {"0031_engine_definitions_stage", "0036_widget_name", "0042_skill_published_loading"},
    "tools": {"tools_0001_gateway", "tools_0020_drop_security_reviews"},
    "platform": {"0006_roles", "0013_team_lifecycle", "0017_signin_domain_verification"},
}
OFFLINE_URL = "postgresql+asyncpg://offline:offline@localhost:1/offline"


def chains() -> list[str]:
    return [line.strip() for line in CHAINS.read_text().splitlines() if line.strip() and not line.startswith("#")]


def runtime_role(chain: str) -> str:
    return f"ops_{chain}_runtime"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass
class Checkout:
    """A git ref exported to a folder with its own environment, so a script reflects that commit and nothing else."""

    ref: str
    root: Path
    commit: str

    def has(self, chain: str) -> bool:
        return (self.root / "services" / f"{chain}-service" / "migrations").is_dir()

    def scripts(self, chain: str) -> ScriptDirectory:
        return ScriptDirectory(str(self.root / "services" / f"{chain}-service" / "migrations"))

    def head(self, chain: str) -> str | None:
        if not self.has(chain):
            return None
        heads = self.scripts(chain).get_heads()
        if len(heads) != 1:
            raise SystemExit(f"{self.ref}: {chain}-service has {len(heads)} heads; merge them first")
        return heads[0]

    def env(self, database: str) -> dict[str, str]:
        return {
            **os.environ,
            "OPS_ROOT": str(self.root),
            "ALEMBIC": str(self.root / ".venv" / "bin" / "alembic"),
            "PYTHON": str(self.root / ".venv" / "bin" / "python"),
            "OPS_DATABASE_URL": database,
            "OPS_MIGRATE_SKIP_BOOTSTRAP": "1",
            "VIRTUAL_ENV": "",
        }

    def migrate(self, database: str, *targets: str) -> None:
        """deploy/images/migrate.sh from this checkout of the tool, run against the exported ref's chains."""
        run = subprocess.run(
            ["sh", str(MIGRATE), *targets], env=self.env(database), capture_output=True, text=True, check=False
        )
        if run.returncode:
            raise SystemExit(
                f"migrate {' '.join(targets)} at {self.ref} failed:\n{run.stdout[-1500:]}{run.stderr[-3000:]}"
            )

    def declared_tables(self, chain: str) -> set[str]:
        """The tables the service's own code declares (chain_tables.py, run in the service's environment)."""
        run = subprocess.run(
            [str(self.root / ".venv" / "bin" / "python"), str(Path(__file__).resolve().parent / "chain_tables.py")],
            cwd=self.root / "services" / f"{chain}-service",
            env=self.env(OFFLINE_URL),
            capture_output=True,
            text=True,
            check=False,
        )
        if run.returncode:
            raise SystemExit(f"{chain}-service: reading its declared tables failed: {run.stderr[-1500:]}")
        return set(json.loads(run.stdout))

    def alembic_sql(self, chain: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.root / ".venv" / "bin" / "alembic"), *args, "--sql"],
            cwd=self.root / "services" / f"{chain}-service",
            env=self.env(OFFLINE_URL),
            capture_output=True,
            text=True,
            check=False,
        )


@contextlib.contextmanager
def exported(ref: str) -> Generator[Checkout]:
    if ref == ".":
        # This folder as it is, for a run inside an export (no .git), such as deploy/compose/proof.sh's.
        yield Checkout(".", ROOT, os.environ.get("OPS_COMMIT", "unversioned"))
        return
    commit = subprocess.run(["git", "rev-parse", ref], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    with tempfile.TemporaryDirectory(prefix="ops-schema-") as tmp:
        archive = subprocess.Popen(["git", "archive", commit.strip()], cwd=ROOT, stdout=subprocess.PIPE)
        subprocess.run(["tar", "-x", "-C", tmp], stdin=archive.stdout, check=True)
        archive.wait()
        env = {**os.environ, "VIRTUAL_ENV": ""}
        sync = subprocess.run(
            ["uv", "sync", "--frozen", "--no-dev", "--quiet"],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if sync.returncode:
            raise SystemExit(f"uv sync at {ref} failed: {sync.stderr[-2000:]}")
        yield Checkout(ref, Path(tmp), commit.strip())


@contextlib.contextmanager
def scratch(dialect: Postgres, prefix: str) -> Generator[str]:
    url = dialect.create(prefix)
    try:
        yield url
    finally:
        dialect.drop(url)


# --- ddl ------------------------------------------------------------------------------------------------------------


@dataclass
class Baseline:
    preamble: str
    schema: list[Entry]
    rows: Dump
    owner: dict[str, str]  # entry key -> chain
    version_tables: dict[str, str]  # chain -> table
    heads: dict[str, str]
    roles: dict[str, dict[str, bool]]
    order: list[str] = field(default_factory=lambda: [])


def build_baseline(dialect: Postgres, checkout: Checkout) -> Baseline:
    with scratch(dialect, "ops_ddl") as url:
        owner: dict[str, str] = {}
        version_tables: dict[str, str] = {}
        heads: dict[str, str] = {}
        seen_versions: set[str] = set()
        order = [c for c in chains() if checkout.has(c)]
        for chain in order:
            checkout.migrate(dialect.sqlalchemy_url(url), chain)
            for e in dialect.dump_schema(url).entries:
                owner.setdefault(e.key, chain)
            new = set(dialect.version_rows(url)) - seen_versions
            if len(new) != 1:
                raise SystemExit(
                    f"{chain}-service: expected one new version table after its chain, found {sorted(new)}"
                )
            version_tables[chain] = new.pop()
            seen_versions.add(version_tables[chain])
            heads[chain] = checkout.head(chain) or ""
        final = dialect.dump_schema(url)
        rows = dialect.dump_rows(url, dialect.tables_with_rows(url))
        granted: set[str] = set()
        for e in final.entries:
            granted |= dialect.grantees(e)
        roles = dialect.roles(url, granted)
    table_chain = {e.name: owner[e.key] for e in final.entries if e.type == "TABLE"}
    for e in rows.entries:
        owner[e.key] = table_chain.get(e.name, order[0])
    return Baseline(final.preamble, final.entries, rows, owner, version_tables, heads, roles, order)


def memberships(
    dialect: Postgres,
    schema: list[Entry],
    *,
    runtime: dict[str, str],
    tables: dict[str, list[str]],
    sequences: dict[str, list[str]],
    roles: set[str],
) -> dict[str, set[str]]:
    """Per runtime role, the roles it switches to (SET LOCAL ROLE): every role of `roles` that its own tables and
    sequences grant to, never another runtime role. roles.sql and grants.sql both grant these."""
    roles = roles - set(runtime.values())
    members: dict[str, set[str]] = {}
    for e in schema:
        if e.type != "ACL":
            continue
        obj = dialect.granted_object(e)
        for chain, role in runtime.items():
            if obj in tables.get(chain, []) or obj in sequences.get(chain, []):
                members.setdefault(role, set()).update(dialect.grantees(e) & roles)
    return members


def write_ddl(dialect: Postgres, checkout: Checkout, out: Path) -> dict[str, Any]:
    b = build_baseline(dialect, checkout)
    out.mkdir(parents=True, exist_ok=True)
    head = (
        f"-- Ops AI schema at {checkout.ref} ({checkout.commit[:12]}), from deploy/database/schema.py; do not edit.\n"
    )
    files: dict[str, str] = {}
    tables: dict[str, list[str]] = {c: [] for c in b.order}
    sequences: dict[str, list[str]] = {c: [] for c in b.order}
    read_only: dict[str, list[str]] = {c: [] for c in b.order}
    existing = {e.name for e in b.schema if e.type == "TABLE"}
    # A service's tables: the ones its chain creates, and the ones its code declares (a table another chain made,
    # such as gateway_calls, which tools-service writes).
    uses: dict[str, set[str]] = {c: checkout.declared_tables(c) & existing for c in b.order}
    for e in b.schema:
        chain = b.owner[e.key]
        if e.type == "TABLE":
            uses[chain].add(e.name)
        elif e.type == "SEQUENCE":
            sequences[chain].append(e.name)
    for chain in b.order:
        for name in sorted(uses[chain]):
            if name in b.version_tables.values():
                if b.version_tables[chain] == name:
                    read_only[chain].append(name)
            else:
                tables[chain].append(name)
    runtime = {c: runtime_role(c) for c in b.order}
    members = memberships(dialect, b.schema, runtime=runtime, tables=tables, sequences=sequences, roles=set(b.roles))
    files["roles.sql"] = head + dialect.roles_script(MIGRATOR, runtime, b.roles, members)
    for i, chain in enumerate(b.order, 1):
        mine = [e for e in b.schema if b.owner[e.key] == chain] + [e for e in b.rows.entries if b.owner[e.key] == chain]
        files[f"{i:02d}-{chain}.sql"] = (
            head
            + f"-- {chain}-service: the objects its chain creates, for review. Apply bundle.sql, not these.\n"
            + b.preamble
            + "".join(render(e) for e in mine)
        )
    files["bundle.sql"] = (
        head
        + f"-- Run as {MIGRATOR} on an empty database, after roles.sql; then grants.sql.\n"
        + b.preamble
        + "".join(render(e) for e in b.schema)
        + b.rows.preamble
        + "".join(render(e) for e in b.rows.entries)
    )
    files["grants.sql"] = head + dialect.grants_script(runtime, tables, sequences, read_only, members)
    for name, text in files.items():
        (out / name).write_text(text)
    manifest = {
        "ref": checkout.ref,
        "commit": checkout.commit,
        "dialect": dialect.name,
        "migrator": MIGRATOR,
        "chains": [
            {
                "name": c,
                "head": b.heads[c],
                "versionTable": b.version_tables[c],
                "runtimeRole": runtime[c],
                "tables": tables[c],
                "sequences": sequences[c],
            }
            for c in b.order
        ],
        "files": {n: sha256(t) for n, t in sorted(files.items())},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    write_sums(out)
    return manifest


def write_sums(out: Path) -> None:
    names = sorted(p.name for p in out.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text("".join(f"{sha256((out / n).read_text())}  {n}\n" for n in names))


# --- upgrade-sql ----------------------------------------------------------------------------------------------------

_TX = re.compile(r"^(BEGIN|COMMIT);\s*$\n?", re.M)
_VERSION_TABLE = re.compile(r"(?:UPDATE|INSERT INTO|CREATE TABLE|DELETE FROM|DROP TABLE) (alembic_version\w*)")


@dataclass
class Step:
    chain: str
    revision: str
    previous: str | None
    up: str
    down: str | None
    version_table: str
    superuser: list[str] = field(default_factory=lambda: [])


def steps(old: Checkout, new: Checkout) -> list[Step]:
    found: list[Step] = []
    refused: list[str] = []
    for chain in chains():
        if not new.has(chain):
            continue
        start, end = old.head(chain), new.head(chain)
        if start == end:
            continue
        revs = list(reversed(list(new.scripts(chain).iterate_revisions(end, start or "base"))))
        for rev in revs:
            prev = rev.down_revision if isinstance(rev.down_revision, str) else None
            if rev.revision in ONLINE_ONLY.get(chain, set()):
                refused.append(f"{chain} {rev.revision}")
                continue
            up = new.alembic_sql(chain, "upgrade", f"{prev or 'base'}:{rev.revision}")
            if up.returncode:
                refused.append(f"{chain} {rev.revision} ({up.stderr.strip().splitlines()[-1][:160]})")
                continue
            down = new.alembic_sql(chain, "downgrade", f"{rev.revision}:{prev or 'base'}")
            table = _VERSION_TABLE.findall(up.stdout)
            if not table:
                raise SystemExit(f"{chain} {rev.revision}: the offline SQL records no version row")
            body, superuser = Postgres.superuser_statements(_TX.sub("", up.stdout).strip())
            found.append(
                Step(
                    chain,
                    rev.revision,
                    prev,
                    body,
                    _TX.sub("", down.stdout).strip() if down.returncode == 0 else None,
                    table[0],
                    superuser,
                )
            )
    if refused:
        raise SystemExit(
            "these revisions cannot render offline; install the baseline of a release after them instead:\n  "
            + "\n  ".join(refused)
        )
    return found


def write_upgrade(dialect: Postgres, old: Checkout, new: Checkout, out: Path) -> list[Step]:
    found = steps(old, new)
    out.mkdir(parents=True, exist_ok=True)
    head = (
        f"-- Ops AI schema upgrade {old.ref} ({old.commit[:12]}) to {new.ref} ({new.commit[:12]}), generated by\n"
        "-- deploy/database/schema.py; do not edit. Run as the migrator. Each step checks its version row, then runs\n"
        f"-- in its own transaction; then run grants.sql from {new.ref}'s baseline.\n\n"
    )
    up = [head]
    for s in found:
        up.append(
            f"-- step {s.chain} {s.previous or 'base'} -> {s.revision}  sha256 {sha256(s.up)}\n"
            + dialect.guard(s.version_table, s.previous)
            + "BEGIN;\n"
            + s.up
            + "\nCOMMIT;\n\n"
        )
    down = [head.replace("upgrade", "downgrade", 1)]
    for s in reversed(found):
        if s.down is None:
            down.append(f"-- step {s.chain} {s.revision} -> {s.previous or 'base'}: no downgrade; restore a backup\n\n")
            continue
        down.append(
            f"-- step {s.chain} {s.revision} -> {s.previous or 'base'}  sha256 {sha256(s.down)}\n"
            + dialect.guard(s.version_table, s.revision)
            + "BEGIN;\n"
            + s.down
            + "\nCOMMIT;\n\n"
        )
    roles = [f"-- step {s.chain} {s.revision}\n" + "\n".join(s.superuser) + "\n\n" for s in found if s.superuser]
    (out / "upgrade-roles.sql").write_text(
        head.replace("Run as the migrator.", "Run as a superuser, before upgrade.sql; every statement is guarded.", 1)
        + ("".join(roles) or "-- No step needs a superuser.\n")
    )
    (out / "upgrade.sql").write_text("".join(up))
    (out / "downgrade.sql").write_text("".join(down))
    write_sums(out)
    return found


# --- drift and diff ------------------------------------------------------------------------------------------------


def _ours(dialect: Postgres, line: str) -> bool:
    """A grant to a runtime role or the migrator: an install adds those (grants.sql, roles.sql), a migration never."""
    if not line.startswith(("GRANT", "REVOKE")):
        return False
    named = dialect.grantees(Entry("", "", line))
    return bool(named) and named <= {runtime_role(c) for c in chains()} | {MIGRATOR}


def comparable(dialect: Postgres, dump: Dump) -> dict[str, str]:
    """Each object's statements, without the grants an install adds."""
    out: dict[str, str] = {}
    for e in dump.entries:
        body = "\n".join(line for line in e.body.splitlines() if not _ours(dialect, line))
        if body.strip():
            out[e.key] = body
    return out


def differences(dialect: Postgres, expected: Dump, actual: Dump) -> list[str]:
    a = comparable(dialect, dialect.canonical(expected))
    b = comparable(dialect, dialect.canonical(actual))
    lines: list[str] = []
    for key in sorted(set(a) | set(b)):
        if key not in b:
            lines.append(f"missing  {key}")
        elif key not in a:
            lines.append(f"extra    {key}\n" + "\n".join(f"           {line}" for line in b[key].splitlines()))
        elif a[key] != b[key]:
            diff = difflib.unified_diff(a[key].splitlines(), b[key].splitlines(), "expected", "live", lineterm="", n=0)
            lines.append(f"differs  {key}\n" + "\n".join(f"           {line}" for line in list(diff)[2:]))
    return lines


def drift(dialect: Postgres, checkout: Checkout, database: str) -> list[str]:
    recorded = dialect.version_rows(database)
    by_revision = {r.revision: c for c in chains() if checkout.has(c) for r in checkout.scripts(c).walk_revisions()}
    targets: dict[str, str] = {}
    for table, revs in recorded.items():
        for rev in revs:
            chain = by_revision.get(rev)
            if chain is None:
                raise SystemExit(
                    f"{table} records {rev}, which {checkout.ref} does not have; check out the release it came from"
                )
            targets[chain] = rev
    order = [f"{c}={targets[c]}" for c in chains() if c in targets]
    with scratch(dialect, "ops_drift") as url:
        if order:
            checkout.migrate(dialect.sqlalchemy_url(url), *order)
        expected = dialect.dump_schema(url)
    return [f"recorded: {' '.join(order) or 'nothing'}", *differences(dialect, expected, dialect.dump_schema(database))]


# --- cli -------------------------------------------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dialect", default="postgresql", choices=sorted(DIALECTS))
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("ddl")
    d.add_argument("--server", help="required for postgresql; SQL Server compiles without one")
    d.add_argument("--out", type=Path, required=True)
    d.add_argument("--ref", default="HEAD")
    u = sub.add_parser("upgrade-sql")
    u.add_argument("--from", dest="old", required=True)
    u.add_argument("--to", dest="new", default="HEAD")
    u.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("drift")
    r.add_argument("--database")
    r.add_argument("--server")
    r.add_argument("--ref", default="HEAD")
    i = sub.add_parser("install", help="a baseline installed on a trial server (proofs, try.yaml); never production")
    i.add_argument("--server", required=True)
    i.add_argument("--dir", type=Path, required=True)
    i.add_argument("--database", required=True)
    i.add_argument("--passwords", type=Path, required=True, help="ROLE=password lines; written when missing")
    f = sub.add_parser("diff")
    f.add_argument("left")
    f.add_argument("right")
    sub.add_parser("golden", help="deploy/database/golden/mssql from this checkout's models (DIALECT=mssql only)")
    a = ap.parse_args()
    if a.dialect == "mssql":
        # Here, not at the top: mssql.py imports this module's Checkout and helpers.
        import mssql  # noqa: PLC0415

        mssql.run(a)
        return
    if a.cmd == "golden" or (a.cmd in ("ddl", "drift") and not a.server) or (a.cmd == "drift" and not a.database):
        ap.error(f"{a.cmd}: --server (and for drift --database) are required for postgresql; golden is mssql only")
    if a.cmd == "ddl":
        dialect = DIALECTS[a.dialect](a.server)
        with exported(a.ref) as checkout:
            m = write_ddl(dialect, checkout, a.out)
        print(f"ddl: {a.out} at {m['ref']} ({m['commit'][:12]}): {', '.join(sorted(m['files']))}")
        for c in m["chains"]:
            print(f"  {c['name']:<10} {c['head']:<40} {len(c['tables'])} tables, role {c['runtimeRole']}")
    elif a.cmd == "upgrade-sql":
        dialect = DIALECTS[a.dialect]("postgresql://unused@localhost/unused")
        with exported(a.old) as old, exported(a.new) as new:
            found = write_upgrade(dialect, old, new, a.out)
        print(f"upgrade-sql: {a.out}: {len(found)} steps, {sum(s.down is not None for s in found)} with a downgrade")
        for s in found:
            print(f"  {s.chain:<10} {s.previous or 'base'} -> {s.revision}")
    elif a.cmd == "drift":
        dialect = DIALECTS[a.dialect](a.server)
        with exported(a.ref) as checkout:
            found = drift(dialect, checkout, a.database)
        print("\n".join(found))
        print(f"drift: {len(found) - 1} difference(s)")
        sys.exit(1 if len(found) > 1 else 0)
    elif a.cmd == "install":
        dialect = DIALECTS[a.dialect](a.server)
        manifest = json.loads((a.dir / "manifest.json").read_text())
        roles = [manifest["migrator"], *(c["runtimeRole"] for c in manifest["chains"])]
        if not a.passwords.exists():
            a.passwords.touch(mode=0o600)
            a.passwords.write_text("".join(f"{r}={secrets.token_urlsafe(18)}\n" for r in roles))
        passwords = dict(line.split("=", 1) for line in a.passwords.read_text().split())
        dialect.install(a.dir, a.database, passwords)
        print(
            f"install: {a.database} from {a.dir} ({manifest['ref']}); {len(roles)} logins, passwords in {a.passwords}"
        )
    else:
        dialect = DIALECTS[a.dialect](a.left)
        found = differences(dialect, dialect.dump_schema(a.left), dialect.dump_schema(a.right))
        print("\n".join(found) or "diff: none")
        sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
