"""The PostgreSQL dialect of the schema tool (schema.py): scratch databases, schema and row dumps, the version rows,
the guard before an upgrade step, and the roles and grants scripts. Another dialect (SQL Server) implements the same
methods; nothing outside this file speaks PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import asyncpg  # pyright: ignore[reportMissingTypeStubs]

from ops_store.schema import member_ddl

# pg_dump's header before each object: "-- Name: graph_threads; Type: TABLE; Schema: public; Owner: -".
_HEADER = re.compile(r"^-- (?:Data for )?Name: (?P<name>.+?); Type: (?P<type>[^;]+); Schema: (?P<schema>[^;]+);", re.M)
# pg_dump 17.6 and later fence a dump with \restrict and \unrestrict and a random token. The bundles are generated and
# reviewed, and a random line would change every checksum, so the fences are dropped.
_FENCE = re.compile(r"^\\(un)?restrict .*$\n?", re.M)
_GRANTEE = re.compile(r"\bTO (\"?[A-Za-z_][A-Za-z0-9_]*\"?);")
# A statement only a superuser may run: CREATE or ALTER ROLE, or a role granted to a role (GRANT <role> TO, no ON).
_ROLE_STATEMENT = re.compile(r"\b(CREATE|ALTER) ROLE\b|\bGRANT \w+ TO \w+")
_ON_TABLE = re.compile(r"ON (?:TABLE|SEQUENCE) public\.(\"?[A-Za-z_][A-Za-z0-9_]*\"?)")


@dataclass(frozen=True)
class Entry:
    """One object of a dump: its key (type and name) and its statements."""

    type: str
    name: str
    body: str

    @property
    def key(self) -> str:
        return f"{self.type} {self.name}"


@dataclass(frozen=True)
class Dump:
    preamble: str
    entries: list[Entry]


def parse(text: str) -> Dump:
    text = _FENCE.sub("", text)
    matches = list(_HEADER.finditer(text))
    first = text.rfind("--\n", 0, matches[0].start()) if matches else len(text)
    preamble = text[:first].rstrip() + "\n"
    entries: list[Entry] = []
    for i, m in enumerate(matches):
        end = text.rfind("--\n", 0, matches[i + 1].start()) if i + 1 < len(matches) else len(text)
        body = text[text.index("\n", m.end()) + 1 : end]
        body = "\n".join(line.rstrip() for line in body.splitlines() if line.strip() and line.strip() != "--")
        entries.append(Entry(m.group("type"), m.group("name"), body))
    return Dump(preamble, entries)


def render(entry: Entry) -> str:
    return f"--\n-- {entry.type}: {entry.name}\n--\n\n{entry.body}\n\n"


def libpq(url: str) -> str:
    """postgresql://... from the SQLAlchemy form the services read (postgresql+asyncpg://...)."""
    return re.sub(r"^postgresql\+\w+://", "postgresql://", url)


def with_database(url: str, name: str) -> str:
    parts = urlsplit(libpq(url))
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", "", ""))


class Postgres:
    name = "postgresql"

    def __init__(self, server: str) -> None:
        self.server = libpq(server)

    # --- connections and scratch databases -------------------------------------------------------------------------

    async def _connect(self, url: str) -> Any:
        return await asyncpg.connect(libpq(url))  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

    def run(self, coro: Any) -> Any:
        return asyncio.run(coro)

    def create(self, prefix: str) -> str:
        name = f"{prefix}_{secrets.token_hex(4)}"

        async def go() -> None:
            c = await self._connect(self.server)
            try:
                await c.execute(f'CREATE DATABASE "{name}"')
            finally:
                await c.close()

        self.run(go())
        return with_database(self.server, name)

    def drop(self, url: str) -> None:
        name = urlsplit(url).path.lstrip("/")

        async def go() -> None:
            c = await self._connect(self.server)
            try:
                await c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            finally:
                await c.close()

        self.run(go())

    def query(self, url: str, sql: str) -> list[dict[str, Any]]:
        async def go() -> list[dict[str, Any]]:
            c = await self._connect(url)
            try:
                return [dict(r) for r in await c.fetch(sql)]
            finally:
                await c.close()

        return self.run(go())

    def execute(self, url: str, script: str) -> None:
        async def go() -> None:
            c = await self._connect(url)
            try:
                await c.execute(script)
            finally:
                await c.close()

        self.run(go())

    def sqlalchemy_url(self, url: str) -> str:
        return libpq(url).replace("postgresql://", "postgresql+asyncpg://", 1)

    # --- dumps -----------------------------------------------------------------------------------------------------

    def _pg_dump(self, url: str, *args: str) -> str:
        """pg_dump of the server's own major version: a local binary when it is new enough, else the postgres image."""
        major = int(self.query(url, "SHOW server_version_num")[0]["server_version_num"]) // 10000
        local = shutil.which("pg_dump")
        if local:
            out = subprocess.run([local, "--version"], capture_output=True, text=True, check=True).stdout
            if int(re.findall(r"(\d+)\.", out)[0]) >= major:
                return subprocess.run([local, *args, libpq(url)], capture_output=True, text=True, check=True).stdout
        parts = urlsplit(libpq(url))
        host = parts.hostname or "localhost"
        docker_host = "host.docker.internal" if host in ("localhost", "127.0.0.1") else host
        netloc = f"{parts.username}@{docker_host}:{parts.port or 5432}"
        target = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
        cmd = ["docker", "run", "--rm", "-e", "PGPASSWORD", f"postgres:{major}-alpine", "pg_dump", *args, target]
        env = {**os.environ, "PGPASSWORD": parts.password or ""}
        return subprocess.run(cmd, capture_output=True, text=True, check=True, env=env).stdout

    def dump_schema(self, url: str) -> Dump:
        # Objects carry no owner: whoever applies the bundle (the migrator) owns them. Grants are kept.
        dump = parse(self._pg_dump(url, "--schema-only", "--no-owner", "--schema=public"))
        # The schema itself exists in every new database; the bundle fills it.
        return Dump(dump.preamble, [e for e in dump.entries if not (e.type == "SCHEMA" and e.name == "public")])

    def canonical(self, dump: Dump) -> Dump:
        """The dump as the server renders it after a restore. A constraint created through SQLAlchemy and the same
        constraint restored from a dump deparse differently (an ARRAY cast moves), so both sides of a comparison go
        through one restore first. Grants are kept as dumped: they name roles the scratch server may not have."""
        objects = [e for e in dump.entries if e.type != "ACL"]
        url = self.create("ops_canon")
        try:
            self.execute(url, dump.preamble + "".join(render(e) for e in objects))
            again = self.dump_schema(url)
        finally:
            self.drop(url)
        return Dump(again.preamble, again.entries + [e for e in dump.entries if e.type == "ACL"])

    def install(self, folder: Path, database: str, passwords: dict[str, str]) -> str:
        """A baseline installed as a DBA would: roles.sql as this server's superuser, a password per login, the
        database owned by the migrator, then bundle.sql and grants.sql as the migrator. For proofs and trials; a bank's
        DBA runs the same files with their own tools. Returns the database's URL for the migrator."""
        self.execute(self.server, (folder / "roles.sql").read_text())
        for role, password in passwords.items():
            self.execute(self.server, f"ALTER ROLE {role} PASSWORD '{password}'")
        self.execute(self.server, f'CREATE DATABASE "{database}" OWNER ops_migrator')
        parts = urlsplit(self.server)
        netloc = f"ops_migrator:{passwords['ops_migrator']}@{parts.hostname}:{parts.port or 5432}"
        url = urlunsplit((parts.scheme, netloc, f"/{database}", "", ""))
        self.execute(url, (folder / "bundle.sql").read_text())
        self.execute(url, (folder / "grants.sql").read_text())
        return url

    @staticmethod
    def superuser_statements(sql: str) -> tuple[str, list[str]]:
        """Splits out what only a superuser may run (creating or altering roles, granting one to a login), so a step
        runs as the migrator and those statements go to a script a superuser runs first. Statements are separated by
        blank lines, as Alembic renders them."""
        kept: list[str] = []
        moved: list[str] = []
        for statement in re.split(r"\n\s*\n", sql):
            if _ROLE_STATEMENT.search(statement):
                moved.append(statement.strip())
                kept.append("-- (a role statement here is in upgrade-roles.sql, run first by a superuser)")
            else:
                kept.append(statement)
        return "\n\n".join(kept), moved

    def tables_with_rows(self, url: str) -> list[str]:
        names = [
            r["table_name"]
            for r in self.query(
                url,
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_type = 'BASE TABLE' ORDER BY table_name",
            )
        ]
        return [n for n in names if self.query(url, f'SELECT EXISTS (SELECT 1 FROM public."{n}") AS has')[0]["has"]]

    def dump_rows(self, url: str, tables: Iterable[str]) -> Dump:
        """The rows a fresh migration writes (version rows, reference rows), as INSERT statements."""
        args = ["--data-only", "--column-inserts", "--no-owner"]
        for t in tables:
            args += ["-t", f'public."{t}"']
        return parse(self._pg_dump(url, *args))

    def version_rows(self, url: str) -> dict[str, list[str]]:
        tables = [
            r["table_name"]
            for r in self.query(
                url,
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name LIKE 'alembic_version%'",
            )
        ]
        return {t: [r["version_num"] for r in self.query(url, f'SELECT version_num FROM public."{t}"')] for t in tables}

    def roles(self, url: str, names: Iterable[str]) -> dict[str, dict[str, bool]]:
        wanted = sorted(set(names))
        if not wanted:
            return {}
        listed = ", ".join(f"'{n}'" for n in wanted)
        rows = self.query(
            url, f"SELECT rolname, rolcanlogin, rolbypassrls, rolinherit FROM pg_roles WHERE rolname IN ({listed})"
        )
        return {
            r["rolname"]: {"login": r["rolcanlogin"], "bypassrls": r["rolbypassrls"], "inherit": r["rolinherit"]}
            for r in rows
        }

    # --- what a dump's grants name --------------------------------------------------------------------------------

    @staticmethod
    def grantees(entry: Entry) -> set[str]:
        return {g.strip('"') for g in _GRANTEE.findall(entry.body) if g.upper() != "PUBLIC"}

    @staticmethod
    def granted_object(entry: Entry) -> str | None:
        m = _ON_TABLE.search(entry.body)
        return m.group(1).strip('"') if m else None

    # --- scripts ---------------------------------------------------------------------------------------------------

    @staticmethod
    def guard(version_table: str, expected: str | None) -> str:
        """Raises before a step's DDL when the database is not at the revision the step starts from."""
        if expected is None:
            check = (
                f"to_regclass('public.{version_table}') IS NULL OR NOT EXISTS (SELECT 1 FROM public.{version_table})"
            )
            want = "no version row"
        else:
            check = f"EXISTS (SELECT 1 FROM public.{version_table} WHERE version_num = '{expected}')"
            want = expected
        return (
            "DO $$ BEGIN\n"
            f"  IF NOT ({check}) THEN\n"
            f"    RAISE EXCEPTION 'this step needs {version_table} at {want}';\n"
            "  END IF;\nEND $$;\n"
        )

    @staticmethod
    def roles_script(
        migrator: str, runtime: dict[str, str], granted: dict[str, dict[str, bool]], members: dict[str, set[str]]
    ) -> str:
        """Run once per server by a superuser. `granted`: the NOLOGIN roles the schema grants to, with their attributes;
        `members`: per runtime role, the granted roles it switches to (SET LOCAL ROLE)."""

        def create(role: str, attrs: str) -> str:
            return (
                f"DO $$ BEGIN CREATE ROLE {role} {attrs}; "
                f"EXCEPTION WHEN duplicate_object THEN ALTER ROLE {role} {attrs}; END $$;\n"
            )

        out = [
            "-- Roles for Ops AI, run once per server by a superuser before the bundle. Set each login's password\n"
            "-- (ALTER ROLE <role> PASSWORD '...'), then create the database owned by the migrator:\n"
            f"--   CREATE DATABASE <name> OWNER {migrator};\n\n",
            "-- The roles the schema's grants and policies name; the services switch to them per transaction.\n",
        ]
        for role, a in sorted(granted.items()):
            attrs = " ".join(
                [
                    "LOGIN" if a["login"] else "NOLOGIN",
                    "BYPASSRLS" if a["bypassrls"] else "NOBYPASSRLS",
                    "INHERIT" if a["inherit"] else "NOINHERIT",
                ]
            )
            out.append(create(role, attrs))
        out.append(
            "\n-- The migrator owns every object and applies the bundle and each upgrade; it is not a superuser.\n"
            "-- It may switch to the roles above, as the first-admin step does.\n"
        )
        out.append(create(migrator, "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"))
        for target in sorted(granted):
            out.append(f"GRANT {target} TO {migrator};\n")
        out.append(
            "\n-- One login per service: DML on its own tables (grants.sql), no DDL, row-level security applies.\n"
        )
        for chain, role in runtime.items():
            out.append(f"-- {chain}-service\n")
            out.append(create(role, "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS INHERIT"))
            for target in sorted(members.get(role, set())):
                out.append(f"GRANT {target} TO {role};\n")
        return "".join(out)

    @staticmethod
    def grants_script(
        runtime: dict[str, str],
        tables: dict[str, list[str]],
        sequences: dict[str, list[str]],
        read_only: dict[str, list[str]],
        members: dict[str, set[str]],
    ) -> str:
        """Run by the migrator after the bundle and after every upgrade; every statement can run again. `members`: per
        runtime role, the roles it switches to, as roles.sql grants them. A role a migration added after roles.sql ran
        reaches its login here, run as a superuser (staging's deploy); as the migrator each is already a member, from
        roles.sql or the step's upgrade-roles.sql, and the statement changes nothing (c-444)."""
        out = [
            "-- Each service's runtime role: DML on its own tables, its sequences, read on its version table.\n",
            "-- Only the owner creates objects: some server templates still grant CREATE on public to PUBLIC.\n",
            "REVOKE CREATE ON SCHEMA public FROM PUBLIC;\n",
        ]
        for chain, role in runtime.items():
            out.append(f"\n-- {chain}-service\nGRANT USAGE ON SCHEMA public TO {role};\n")
            dml = tables.get(chain, [])
            if dml:
                listed = ", ".join(f"public.{t}" for t in dml)
                out.append(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {listed} TO {role};\n")
            seqs = sequences.get(chain, [])
            if seqs:
                out.append(f"GRANT USAGE, SELECT ON SEQUENCE {', '.join(f'public.{s}' for s in seqs)} TO {role};\n")
            ro = read_only.get(chain, [])
            if ro:
                out.append(f"GRANT SELECT ON TABLE {', '.join(f'public.{t}' for t in ro)} TO {role};\n")
            for target in sorted(members.get(role, set())):
                out.append(member_ddl(target, role) + ";\n")
        return "".join(out)
