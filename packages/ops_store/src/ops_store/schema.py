"""A service's schema is its store metadata: every table, index, constraint and default its migrations create is also
in the SQLAlchemy tables its store defines, so DDL for any supported database is compiled from one source.

  sa.Table("cases", metadata, ..., info=TENANT_SCOPED)   # the database isolates this table by tenant
  differences(conn, [metadata])                           # every way the migrated database and the metadata differ
  unowned(conn, [metadata, ...])                          # tables in the database that no metadata defines

`TENANT_SCOPED` means the database itself hides other tenants' rows from this table (forced row-level security on
PostgreSQL, a security policy on SQL Server). DDL for that isolation is generated from the marker, so it is held equal
to what the database enforces: a marked table the database does not isolate, or the reverse, is a difference.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Sequence
from typing import Any, Literal

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

TENANT_KEY = "tenant_scoped"
TENANT_SCOPED: dict[str, Any] = {TENANT_KEY: True}
# A team's work or asset: every read names the caller's team through `ops_store.team_scope.team_visible` (c-407), and
# `packages/ops_store/tests/test_team_reads.py` fails on a read that does not. Every row has a team (c-507): the
# database policy reads only the acting team's rows, and nothing is shared across teams.
TEAM_KEY = "team_owned"
# A table whose rows belong to a team-owned parent (an agent's versions): read through the parent's team.
TEAM_VIA_KEY = "team_owned_via"


def team_owned(column: str = "team_id") -> dict[str, Any]:
    """The marker for a team-owned table whose team is in `column` (`team` in files and documents)."""
    return {TEAM_KEY: column}


TEAM_OWNED: dict[str, Any] = team_owned()


def team_owned_via(parent: str, column: str) -> dict[str, Any]:
    """The marker for a table read through the team of its parent table `parent`, joined on `column` = parent.id."""
    return {TEAM_VIA_KEY: (parent, column)}


def tenant_scoped(table: sa.Table) -> bool:
    return bool(table.info.get(TENANT_KEY))


def tables(metadatas: Iterable[sa.MetaData], exclude: Collection[str] = ()) -> dict[str, sa.Table]:
    return {name: t for m in metadatas for name, t in m.tables.items() if name not in exclude}


def isolated_tables(conn: sa.Connection) -> dict[str, str]:
    """The tables the database isolates on its own and how, `team` or `tenant`, read from the database rather than
    from migrations: a table with the generated `{t}_isolation` policy is isolated by team, any other by tenant."""
    if conn.dialect.name == "postgresql":
        # Forced, so the owner the services connect as is filtered too; enabled alone exempts the owner.
        rows = conn.execute(
            sa.text(
                "SELECT c.relname, bool_or(p.polname = c.relname || '_isolation')"
                " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                " LEFT JOIN pg_policy p ON p.polrelid = c.oid"
                " WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p')"
                " AND c.relrowsecurity AND c.relforcerowsecurity GROUP BY c.relname"
            )
        )
        return {str(r[0]): "team" if r[1] else "tenant" for r in rows}
    if conn.dialect.name == "mssql":
        rows = conn.execute(
            sa.text(
                "SELECT o.name, MAX(CASE WHEN p.name = o.name + N'_isolation' THEN 1 ELSE 0 END)"
                " FROM sys.security_predicates sp JOIN sys.security_policies p ON p.object_id = sp.object_id"
                " JOIN sys.objects o ON o.object_id = sp.target_object_id"
                " WHERE p.is_enabled = 1 AND SCHEMA_NAME(o.schema_id) = SCHEMA_NAME() GROUP BY o.name"
            )
        )
        return {str(r[0]): "team" if r[1] else "tenant" for r in rows}
    raise NotImplementedError(f"isolated_tables: no reader for {conn.dialect.name}")


def differences(conn: sa.Connection, metadatas: Sequence[sa.MetaData], exclude: Collection[str] = ()) -> list[str]:
    """Every way the database on `conn` differs from `metadatas` for the tables they define (less `exclude`), one line
    each: Alembic's comparison (tables, columns, types, nullability, indexes, unique keys, foreign keys), plus server
    defaults by presence, CHECK constraints and computed columns by name, and each table's isolation kind (team or
    tenant, from its markings) against what the database enforces."""
    ours = tables(metadatas, exclude)

    def include(name: str | None, type_: str, _parent: dict[str, str | None]) -> bool:
        return type_ != "table" or name in ours

    context = MigrationContext.configure(
        conn,
        # Alembic's own default comparison fails on a computed column (its user hook reads `.arg` off a Computed), so
        # defaults are compared below from the inspector.
        opts={"compare_type": True, "compare_server_default": False, "include_name": include},
    )
    # Alembic compares a list of MetaData as one (as env.py's target_metadata), though the signature names one.
    out = [_describe(d) for d in compare_metadata(context, list(metadatas))]  # pyright: ignore[reportArgumentType]
    inspector = sa.inspect(conn)
    present = set(inspector.get_table_names())
    for name, table in sorted(ours.items()):
        if name not in present:
            continue  # compare_metadata reported it
        want = {c.name for c in table.constraints if isinstance(c, sa.CheckConstraint) and isinstance(c.name, str)}
        have = {str(c["name"]) for c in inspector.get_check_constraints(name)}
        out += [f"check {name}.{c} in the database, not in metadata" for c in sorted(have - want)]
        out += [f"check {name}.{c} in metadata, not in the database" for c in sorted(want - have)]
        reflected = {str(c["name"]): c for c in inspector.get_columns(name)}
        computed = {n for n, c in reflected.items() if c.get("computed")}
        declared = {c.name for c in table.columns if c.computed is not None}
        out += [f"computed column {name}.{c} differs" for c in sorted(computed ^ declared)]
        for column in table.columns:
            seen = reflected.get(column.name)
            if seen is None or column.name in computed | declared:
                continue
            # Only presence: each database renders a default's text its own way. A sequence is the key's, not a default.
            db_default = seen.get("default")
            has = db_default is not None and not str(db_default).startswith("nextval(")
            if has != (column.server_default is not None):
                where = "the database" if has else "metadata"
                out.append(f"default {name}.{column.name} only in {where}")
    enforced = {t: k for t, k in isolated_tables(conn).items() if t in ours}
    expected = {name: k for name, t in ours.items() if (k := isolation_kind(t)) in ("team", "tenant")}
    out += [
        f"tenant {t} is isolated in the database, not marked TENANT_SCOPED"
        for t in sorted(set(enforced) - set(expected))
    ]
    out += [
        f"tenant {t} is marked TENANT_SCOPED, not isolated in the database"
        for t in sorted(set(expected) - set(enforced))
    ]
    out += [
        f"isolation {t} is marked {expected[t]}-isolated, the database isolates it by {enforced[t]}"
        for t in sorted(set(expected) & set(enforced))
        if expected[t] != enforced[t]
    ]
    return out


# Isolation DDL, generated from the markings (c-410; design: c-408 spec section 2) ---------------------------------

SYSTEM_KEY = "system_reason"
IsolationKind = Literal["team", "tenant", "system"]
# The schema SQL Server's predicate functions and policies live in.
MSSQL_SECURITY = "ops_security"


def system(reason: str) -> dict[str, Any]:
    """The marker for a table with no tenant column, reached only through `ops_store.isolation.system_tx` (leases,
    timers, inbox, fences): no policy and no grant to the request role. `reason` says why it holds no tenant."""
    if not reason.strip():
        raise ValueError("system() needs a reason")
    return {SYSTEM_KEY: reason}


def isolation_kind(table: sa.Table) -> IsolationKind | None:
    """How the database isolates `table`, from its markings: `team` for a tenant-scoped table that is also team-owned
    with its own team column, `tenant` for any other tenant-scoped table, `system`, or None for a table not yet marked.
    A team-owned table that is not tenant-scoped (no tenant column yet) is held by the query filter alone."""
    if tenant_scoped(table):
        return "team" if isinstance(table.info.get(TEAM_KEY), str) else "tenant"
    if table.info.get(SYSTEM_KEY):
        return "system"
    return None


def tenant_column(table: sa.Table) -> sa.Column[Any]:
    """The column a tenant-scoped table is isolated by: tenant_id, or a tenant table's own single-column key."""
    if "tenant_id" in table.c:
        return table.c.tenant_id
    key = list(table.primary_key.columns)
    if table.name == "tenants" and len(key) == 1:
        return key[0]
    raise ValueError(f"{table.name} is TENANT_SCOPED but has no tenant_id column")


def team_column(table: sa.Table) -> sa.Column[Any]:
    name = table.info.get(TEAM_KEY)
    if not isinstance(name, str) or name not in table.c:
        raise ValueError(f"{table.name} is not team-owned with a team column")
    return table.c[name]


def _pg_predicates(table: sa.Table, kind: IsolationKind, *, reads_no_team: bool = False) -> tuple[str, str]:
    """The read (USING) and write (WITH CHECK) conditions of the table's one policy. Each setting is read in a scalar
    subquery, which PostgreSQL evaluates once per statement (an InitPlan) instead of once per row. `reads_no_team` is
    the policy before c-507, which also read rows with no team; only a downgrade past c-507 asks for it."""

    def setting(name: str) -> str:
        return f"(SELECT current_setting('{name}', true))"

    tenant = f"{tenant_column(table).name} = {setting('app.tenant_id')}"
    if kind == "tenant":
        return tenant, tenant
    team = team_column(table).name
    wide = f"{setting('app.scope')} = 'tenant'"
    own = f"{team} = {setting('app.team_id')}"
    no_team = f" OR {team} IS NULL" if reads_no_team else ""
    return f"{tenant} AND ({wide}{no_team} OR {own})", f"{tenant} AND ({wide} OR {own})"


def isolation_ddl(
    table: sa.Table, dialect: str, *, kind: IsolationKind | None = None, chain: str = "", reads_no_team: bool = False
) -> list[str]:
    """The statements that make the database isolate `table` as its markings say (or as `kind` says, for a migration's
    downgrade), each runnable on its own and safe to repeat. PostgreSQL: forced row-level security and one policy,
    `{t}_isolation` (team) or `{t}_tenant`, replacing the other, since permissive policies OR together. SQL Server: one
    security policy over the chain's predicate functions (`security_ddl` creates them). A system or unmarked table
    gets none."""
    kind = kind or isolation_kind(table)
    if kind not in ("team", "tenant"):
        return []
    t = table.name
    name, other = (f"{t}_isolation", f"{t}_tenant") if kind == "team" else (f"{t}_tenant", f"{t}_isolation")
    if dialect == "postgresql":
        read, write = _pg_predicates(table, kind, reads_no_team=reads_no_team)
        return [
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS {other} ON {t}",
            f"DROP POLICY IF EXISTS {name} ON {t}",
            f"CREATE POLICY {name} ON {t} USING ({read}) WITH CHECK ({write})",
        ]
    if dialect == "mssql":
        if not chain:
            raise ValueError("SQL Server predicates are per chain; name it")
        args = tenant_column(table).name + (f", {team_column(table).name}" if kind == "team" else "")
        fn = f"{MSSQL_SECURITY}.{chain}_{kind}"
        drop = "IF OBJECT_ID(N'{0}', N'SP') IS NOT NULL DROP SECURITY POLICY {0}"
        return [
            drop.format(f"{MSSQL_SECURITY}.{other}"),
            drop.format(f"{MSSQL_SECURITY}.{name}"),
            f"CREATE SECURITY POLICY {MSSQL_SECURITY}.{name}\n"
            f"    ADD FILTER PREDICATE {fn}_read({args}) ON dbo.{t},\n"
            f"    ADD BLOCK PREDICATE {fn}_write({args}) ON dbo.{t} AFTER INSERT,\n"
            f"    ADD BLOCK PREDICATE {fn}_write({args}) ON dbo.{t} AFTER UPDATE\n"
            "    WITH (STATE = ON, SCHEMABINDING = ON)",
        ]
    raise NotImplementedError(f"isolation_ddl: no policies for {dialect}")


def role_ddl(name: str, *, bypass: bool = False) -> str:
    """PostgreSQL: a role with no login a migration grants tables to; `bypass` makes it a system role that row-level
    security does not apply to. Roles are cluster-wide, so one made by another database is left as it is."""
    attrs = "NOLOGIN BYPASSRLS" if bypass else "NOLOGIN"
    return f"DO $$ BEGIN CREATE ROLE {name} {attrs}; EXCEPTION WHEN duplicate_object THEN NULL; END $$"


def member_ddl(role: str, login: str) -> str:
    """PostgreSQL: makes a service's runtime login a member of a role its transactions switch to (SET LOCAL ROLE).
    Changes nothing when the login does not exist (services that connect as the superuser) or is a member already, so
    it runs as the migrator wherever roles.sql granted the role. A migration that adds such a role grants it with this:
    roles.sql runs once per server, so a login made before the role existed is otherwise never a member (c-444)."""
    return (
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{login}') "
        f"AND NOT pg_has_role('{login}', '{role}', 'MEMBER') THEN GRANT {role} TO {login}; END IF; END $$"
    )


def isolation_drop_ddl(table: sa.Table, dialect: str) -> list[str]:
    """The reverse of `isolation_ddl` for a table that had no isolation before (a migration's downgrade): its generated
    policy gone, row-level security off on PostgreSQL."""
    t = table.name
    names = (f"{t}_isolation", f"{t}_tenant")
    if dialect == "postgresql":
        return [
            *(f"DROP POLICY IF EXISTS {n} ON {t}" for n in names),
            f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY",
            f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY",
        ]
    if dialect == "mssql":
        drop = "IF OBJECT_ID(N'{0}', N'SP') IS NOT NULL DROP SECURITY POLICY {0}"
        return [drop.format(f"{MSSQL_SECURITY}.{n}") for n in names]
    raise NotImplementedError(f"isolation_drop_ddl: no policies for {dialect}")


def security_ddl(
    chain: str, tables: Iterable[sa.Table], *, column_type: Callable[[sa.Column[Any]], str], system_user: str | None
) -> list[str]:
    """SQL Server, for the baseline: the chain's schema, its predicate functions for each kind its tables use, then each
    table's policy. Reads see the context's tenant (and, for a team table, the context's team, or every
    team in a tenant-wide scope); writes must be the context's tenant (and team, unless tenant-wide). `system_user` (the
    agents chain's) passes both: its grants limit what it reads and which columns it updates. Nothing a login can set
    opens another tenant's rows; a missing tenant matches no row."""
    marked = [t for t in tables if isolation_kind(t) in ("team", "tenant")]
    if not marked:
        return []
    out = [f"IF SCHEMA_ID(N'{MSSQL_SECURITY}') IS NULL EXEC (N'CREATE SCHEMA {MSSQL_SECURITY} AUTHORIZATION dbo')"]
    out += [create for _name, create in _mssql_functions(chain, marked, column_type, system_user)]
    for t in marked:
        out.append(isolation_ddl(t, "mssql", chain=chain)[-1])
    return out


def mssql_predicates_ddl(
    chain: str, tables: Iterable[sa.Table], *, column_type: Callable[[sa.Column[Any]], str], system_user: str | None
) -> list[str]:
    """SQL Server, for a migration after the baseline: the predicate functions `tables` need, each created only when it
    does not exist yet, so a migration can run them before `isolation_ddl` on any install."""
    marked = [t for t in tables if isolation_kind(t) in ("team", "tenant")]
    return [
        f"IF OBJECT_ID(N'{name}', N'IF') IS NULL EXEC (N'{create.replace(chr(39), chr(39) * 2)}')"
        for name, create in _mssql_functions(chain, marked, column_type, system_user)
    ]


def mssql_team_predicates_reissue_ddl(
    chain: str,
    team_tables: Sequence[sa.Table],
    *,
    column_type: Callable[[sa.Column[Any]], str],
    system_user: str | None,
    reads_no_team: bool = False,
) -> list[str]:
    """SQL Server, for a migration that changes the team predicate's text (c-507): the functions are schema-bound to
    every policy that uses them, so each of the chain's team tables loses its policy, the team functions are dropped
    and created again, and each policy comes back. `team_tables` must be every team table of the chain at that
    revision, or the drop is refused by a policy still bound to the function."""
    fn = f"{MSSQL_SECURITY}.{chain}_team"
    out = [
        f"IF OBJECT_ID(N'{MSSQL_SECURITY}.{t.name}_isolation', N'SP') IS NOT NULL "
        f"DROP SECURITY POLICY {MSSQL_SECURITY}.{t.name}_isolation"
        for t in team_tables
    ]
    out += [f"IF OBJECT_ID(N'{fn}_{part}', N'IF') IS NOT NULL DROP FUNCTION {fn}_{part}" for part in ("read", "write")]
    functions = _mssql_functions(chain, list(team_tables), column_type, system_user, reads_no_team=reads_no_team)
    out += [f"EXEC (N'{create.replace(chr(39), chr(39) * 2)}')" for _name, create in functions]
    for t in team_tables:
        out += isolation_ddl(t, "mssql", kind="team", chain=chain)
    return out


def _mssql_functions(
    chain: str,
    marked: list[sa.Table],
    column_type: Callable[[sa.Column[Any]], str],
    system_user: str | None,
    *,
    reads_no_team: bool = False,
) -> list[tuple[str, str]]:
    """(name, CREATE FUNCTION) for the read and write predicate of each kind `marked` uses."""
    system = f" OR USER_NAME() = N'{system_user}'" if system_user else ""
    out: list[tuple[str, str]] = []
    for kind in sorted({k for t in marked if (k := isolation_kind(t))}, reverse=True):
        of_kind = [t for t in marked if isolation_kind(t) == kind]
        tenants = {column_type(tenant_column(t)) for t in of_kind}
        if len(tenants) != 1:
            raise ValueError(
                f"{chain}: tenant columns of different types {sorted(tenants)}; one predicate cannot take them"
            )
        (tenant_type,) = tenants
        ctx_tenant = f"CAST(SESSION_CONTEXT(N'tenant_id') AS {tenant_type})"
        fn = f"{MSSQL_SECURITY}.{chain}_{kind}"
        if kind == "tenant":
            params, read, write = (
                f"@tenant_id {tenant_type}",
                f"@tenant_id = {ctx_tenant}",
                f"@tenant_id = {ctx_tenant}",
            )
        else:
            teams = {column_type(team_column(t)) for t in of_kind}
            if len(teams) != 1:
                raise ValueError(f"{chain}: team columns of different types {sorted(teams)}")
            (team_type,) = teams
            ctx_team = f"CAST(SESSION_CONTEXT(N'team_id') AS {team_type})"
            wide = "CAST(SESSION_CONTEXT(N'scope') AS NVARCHAR(16)) = N'tenant'"
            params = f"@tenant_id {tenant_type}, @team_id {team_type}"
            no_team = " OR @team_id IS NULL" if reads_no_team else ""
            read = f"@tenant_id = {ctx_tenant} AND ({wide}{no_team} OR @team_id = {ctx_team})"
            write = f"@tenant_id = {ctx_tenant} AND ({wide} OR @team_id = {ctx_team})"
        out += [
            (
                f"{fn}_read",
                f"CREATE FUNCTION {fn}_read ({params})\nRETURNS TABLE WITH SCHEMABINDING AS RETURN\n"
                f"SELECT 1 AS visible WHERE {read}{system}",
            ),
            (
                f"{fn}_write",
                f"CREATE FUNCTION {fn}_write ({params})\nRETURNS TABLE WITH SCHEMABINDING AS RETURN\n"
                f"SELECT 1 AS allowed WHERE {write}{system}",
            ),
        ]
    return out


def unowned(conn: sa.Connection, metadatas: Sequence[sa.MetaData], exclude: Collection[str] = ()) -> list[str]:
    """Tables in the database that no metadata defines, besides Alembic's version tables and `exclude`."""
    known = tables(metadatas)
    return sorted(
        name
        for name in sa.inspect(conn).get_table_names()
        if name not in known and name not in exclude and not name.startswith("alembic_version")
    )


def _describe(diff: Any) -> str:
    """One line for one of Alembic's difference tuples (or a list of column modifications)."""
    if isinstance(diff, list):
        return "; ".join(_describe(d) for d in diff)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
    kind, *rest = diff
    where = ""
    for part in rest:
        if isinstance(part, sa.Table):
            where = part.name
        elif isinstance(part, sa.Index):
            where = f"{part.table.name if part.table is not None else ''}.{part.name}"
        elif isinstance(part, (sa.Column, sa.Constraint)):
            where = f"{part.table.name}.{part.name}"
        elif isinstance(part, str) and not where:
            where = part
    if kind.startswith("modify_") and len(rest) >= 3:
        table, column = rest[1], rest[2]
        return f"{kind} {table}.{column}: database {rest[-2]!r}, metadata {rest[-1]!r}"
    side = "in metadata, not in the database" if kind.startswith("add_") else "in the database, not in metadata"
    return f"{kind} {where} {side}"
