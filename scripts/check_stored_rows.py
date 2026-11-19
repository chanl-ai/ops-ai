"""Reads every stored row through the typed readers the services use and reports any row a reader refuses. Run it
against a database before a release: a stricter reader (a row model, a `stored()` JSON shape) must refuse no row
already stored.

    uv run python scripts/check_stored_rows.py [--service tools] [--limit 500] [--list]
    OPS_DATABASE_URL=<url> uv run python scripts/check_stored_rows.py            # another environment

The database comes from `OPS_DATABASE_URL`, read through `ops_service_kit.settings.Settings` as every service reads it
(one database holds every service's tables, so `--service` filters the readers, not the connection). The URL is never
printed. Nothing is written: each reader runs in its own transaction, a read-only one on PostgreSQL
(`SET TRANSACTION READ ONLY`), and on both databases every statement is checked before it is sent and anything but a
SELECT stops the run. SQL Server has no read-only transaction; give the script a login that can only read.

Each reader prints `reader  table  read N  refused M`, then one line per refused row with its table, primary key and the
name of the key that failed (never the value), and ends with `stored rows: X read, Y refused`. A row model is checked
with the product's own model on the columns the table holds; a field the model takes from a join or an expression
(missing from the table) is not judged. A JSON column read through `stored()` or a service function is judged by that
reader, with the call site's own defaults. Exit 1 when a row is refused, a reader cannot run, or the login sees only
some tenants' rows (`--visible-only` accepts that last case; the output still says
"checked only rows visible to <role>").
Rows are read as the configured login: no role is switched and no row policy is changed.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import sqlalchemy as sa
from pydantic import BaseModel, ValidationError
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.settings import Settings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "fly"))
from database_url import asyncpg_url, ssl_mode  # shared with deploy/fly/staging/apps.py

BATCH = 200
# Refused rows named per reader before the rest are counted.
NAMED = 20
# A statement may start with one of these; SET only as the transaction setting below.
ALLOWED = ("SELECT", "WITH", "SHOW", "SET TRANSACTION", "ROLLBACK", "COMMIT", "BEGIN")
# The error type pydantic gives a required field the row did not carry.
MISSING = "missing"

# A reader of a JSON column: takes the row, raises when the product's reader would refuse it.
Check = Callable[[Mapping[str, Any]], object]


class NotInVersion(Exception):
    """The module or name a reader needs does not exist in the checked-out code (an older release)."""


def load(path: str) -> Any:
    """`module:attr` (attr may be dotted) imported by name, so a service not asked for is never imported. A module or
    name the code does not have is `NotInVersion`; any other import error is a real one and propagates."""
    module, _, attr = path.partition(":")
    try:
        found: Any = importlib.import_module(module)
    except ModuleNotFoundError as e:
        if e.name and (module == e.name or module.startswith(e.name + ".")):
            raise NotInVersion(path) from e
        raise
    for part in filter(None, attr.split(".")):
        try:
            found = getattr(found, part)
        except AttributeError as e:
            raise NotInVersion(path) from e
    return found


@dataclass(frozen=True)
class Reader:
    service: str
    name: str
    table: str
    # A row model (`module:Class`), or the columns a JSON reader needs with the function that judges one row.
    model: str | None = None
    columns: tuple[str, ...] = ()
    build: Callable[[], Check] | None = None
    # Only rows where `column == value`.
    only: tuple[str, str] | None = None
    # The module whose import defines the table.
    home: str = ""


@dataclass
class Outcome:
    table: str = ""
    absent: bool = False
    read: int = 0
    refused: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    failure: str | None = None


# --- readers ------------------------------------------------------------------------------------------------------


def models(service: str, home: str, pairs: Iterable[tuple[str, str]]) -> list[Reader]:
    """Row models in module `home`, each with the table its rows come from."""
    return [Reader(service, name, table, model=f"{home}:{name}", home=home) for name, table in pairs]


def json_reader(  # noqa: PLR0917
    service: str, name: str, table: str, home: str, columns: tuple[str, ...], build: Callable[[], Check]
) -> Reader:
    return Reader(service, name, table, columns=columns, build=build, home=home)


def _stored(path: str, column: str) -> Callable[[], Check]:
    def build() -> Check:
        reader = load(path)
        return lambda row: reader(row[column])

    return build


def decoded(raw: Any) -> Any:
    """A JSON column kept as text (documents-service, database portability D5) as its row model reads it: parsed, and
    empty text as none."""
    if isinstance(raw, str):
        return json.loads(raw) if raw else None
    return raw


def _each(path: str, column: str) -> Callable[[], Check]:
    """A `stored()` reader applied to every entry of a list column, as `[FIELD(f) for f in entries(...)]` does."""

    def build() -> Check:
        reader = load(path)
        entries = load("ops_service_kit.narrow:entries")
        return lambda row: [reader(entry) for entry in entries(decoded(row[column]))]

    return build


def _request_part(path: str, key: str) -> Callable[[], Check]:
    """A reader applied to each entry of a key of an extraction's stored request."""

    def build() -> Check:
        reader = load(path)
        entries = load("ops_service_kit.narrow:entries")
        an_object = load("ops_service_kit.narrow:an_object")
        return lambda row: [reader(entry) for entry in entries(an_object(decoded(row["request"]), "request").get(key))]

    return build


def _kb_source_config() -> Check:
    config = load("ops_kb.tool_sources:SOURCE_CONFIG")
    return lambda row: config(row["config"] or {})


def _kb_sections() -> Check:
    sections_of = load("ops_kb.service:sections_of")
    return lambda row: sections_of(str(row["slug"]), row["retrieval"] or {}, row["settings"])


def _kb_retrieval() -> Check:
    retrieval, default = load("ops_kb.service:RETRIEVAL"), load("ops_kb.service:DEFAULT_RETRIEVAL")
    return lambda row: retrieval({**default, **(row["retrieval"] or {})})


def _kb_source_settings() -> Check:
    stored = load("ops_kb.source_settings:stored")

    def read(row: Mapping[str, Any]) -> object:
        # kind_of(): a plugin source whose items are one website's pages reads with a website's defaults.
        config = cast("dict[str, Any]", row["config"]) if isinstance(row["config"], dict) else {}
        kind = "web" if row["type"] == "tool" and config.get("site") else str(row["type"])
        return stored(kind, row["settings"] or None)

    return read


def _registry_readers() -> list[Reader]:
    """The versioned registries and typed records, which name their tables and row models on the class."""
    out: list[Reader] = []
    for service, home, cls in (
        ("agents", "ops_agents.store.agent_registry", "AgentRegistry"),
        ("agents", "ops_agents.store.guardrails", "GuardrailRegistry"),
        ("agents", "ops_agents.store.skills", "SkillRegistry"),
        ("agents", "ops_agents.store.widgets", "WidgetRegistry"),
    ):
        out.append(Reader(service, f"{cls} head", f"@{home}:{cls}.head", model=f"@{home}:{cls}.head_row", home=home))
        out.append(
            Reader(service, f"{cls} versions", f"@{home}:{cls}.history", model=f"@{home}:{cls}.version_row", home=home)
        )
    for home, cls in (
        ("ops_agents.store.case_types", "CaseTypeStore"),
        ("ops_agents.store.task_types", "TaskTypeStore"),
    ):
        out.append(
            Reader(
                "agents",
                f"{cls} head",
                f"@{home}:{cls}.head",
                model="ops_agents.store.typed_records:TypeHead",
                home=home,
            )
        )
        out.append(
            Reader(
                "agents",
                f"{cls} versions",
                f"@{home}:{cls}.versions",
                model="ops_agents.store.typed_records:TypeVersion",
                home=home,
            )
        )
    return out


READERS: list[Reader] = [
    # Customer-written JSON first: sign-in settings, then the documents, knowledge and workflow definitions.
    json_reader(
        "platform",
        "PROVIDER_CONFIG",
        "signin_providers",
        "ops_platform.store.signin",
        ("config",),
        _stored("ops_platform.store.signin:PROVIDER_CONFIG", "config"),
    ),
    Reader(
        "platform",
        "OIDC_SIGN_IN",
        "signin_providers",
        columns=("config",),
        only=("kind", "oidc"),
        build=_stored("ops_platform.store.signin:OIDC_SIGN_IN", "config"),
        home="ops_platform.store.signin",
    ),
    Reader(
        "platform",
        "SAML_SIGN_IN",
        "signin_providers",
        columns=("config",),
        only=("kind", "saml"),
        build=_stored("ops_platform.store.signin:SAML_SIGN_IN", "config"),
        home="ops_platform.store.signin",
    ),
    json_reader(
        "documents",
        "FIELD (document type fields)",
        "document_type_versions",
        "ops_documents.store.document_types",
        ("fields",),
        _each("ops_documents.extraction:FIELD", "fields"),
    ),
    json_reader(
        "documents",
        "TEMPLATE (document type templates)",
        "document_type_versions",
        "ops_documents.store.document_types",
        ("templates",),
        _each("ops_documents.extraction:TEMPLATE", "templates"),
    ),
    json_reader(
        "documents",
        "FIELD (extraction request)",
        "extractions",
        "ops_documents.store.extractions",
        ("request",),
        _request_part("ops_documents.extraction:FIELD", "fields"),
    ),
    json_reader(
        "documents",
        "CHECK (extraction request)",
        "extractions",
        "ops_documents.store.extractions",
        ("request",),
        _request_part("ops_documents.extraction:CHECK", "checks"),
    ),
    json_reader(
        "documents",
        "TEMPLATE (extraction request)",
        "extractions",
        "ops_documents.store.extractions",
        ("request",),
        _request_part("ops_documents.extraction:TEMPLATE", "templates"),
    ),
    json_reader(
        "kb",
        "sections_of (base settings)",
        "kb_bases",
        "ops_kb.store.knowledge",
        ("slug", "retrieval", "settings"),
        _kb_sections,
    ),
    json_reader(
        "kb",
        "RETRIEVAL (base retrieval)",
        "kb_bases",
        "ops_kb.store.knowledge",
        ("retrieval",),
        _kb_retrieval,
    ),
    Reader(
        "kb",
        "SOURCE_CONFIG (tool source)",
        "kb_sources",
        columns=("config",),
        only=("type", "tool"),
        build=_kb_source_config,
        home="ops_kb.store.knowledge",
    ),
    json_reader(
        "kb",
        "source_settings.stored (source settings)",
        "kb_sources",
        "ops_kb.store.knowledge",
        ("type", "config", "settings"),
        _kb_source_settings,
    ),
    # Row models.
    *models("platform", "ops_platform.store.signin", [("BreakGlassRow", "signin_break_glass")]),
    *models("platform", "ops_platform.store.policies", [("PolicyRow", "policies")]),
    *models(
        "tools",
        "ops_tools.store.connections",
        [
            ("_AccountRow", "connections"),
            ("OwnAccount", "connections"),
            ("TokenRow", "connection_tokens"),
            ("TeamToken", "connection_tokens"),
            ("HeldToken", "connection_tokens"),
            ("IdleSignIn", "connection_tokens"),
            ("OwnSignIn", "connection_tokens"),
            ("PersonSignIn", "connection_tokens"),
            ("SignIn", "connection_tokens"),
            ("HeldState", "oauth_states"),
        ],
    ),
    *models(
        "agents",
        "ops_agents.store.cases",
        [("CaseRecord", "cases"), ("CaseEventRecord", "case_events")],
    ),
    *models("agents", "ops_agents.store.case_links", [("CaseEmail", "trigger_events"), ("RelatedCase", "cases")]),
    *models(
        "agents",
        "ops_agents.store.memories",
        [("MemoryRecord", "agent_memories"), ("MemoryMatch", "agent_memories"), ("MemoryAuditRecord", "memory_audit")],
    ),
    *models("agents", "ops_agents.store.agent_registry", [("PublishRequestRow", "registry_publish_requests")]),
    *models("agents", "ops_agents.store.review_sources", [("ThreadRow", "graph_threads")]),
    *models("agents", "ops_agents.store.service_events", [("DefinitionRow", "engine_definitions")]),
    *models("agents", "ops_agents.store.task_assists", [("WrittenAssist", "task_assists")]),
    *models("agents", "ops_agents.store.widgets", [("ListedWidget", "registry_widgets")]),
    *_registry_readers(),
    *models(
        "documents",
        "ops_documents.store.document_types",
        [
            ("TypeRow", "document_types"),
            ("VersionRow", "document_type_versions"),
            ("ExampleRow", "document_type_examples"),
            ("SampleRow", "document_type_samples"),
            ("TestRow", "document_type_tests"),
        ],
    ),
    *models(
        "documents",
        "ops_documents.store.extractions",
        [("ExtractionRow", "extractions"), ("CorrectionRow", "extraction_corrections")],
    ),
    *models("documents", "ops_documents.store.readings", [("ReadingRow", "documents_readings")]),
    *models("documents", "ops_documents.store.template_copies", [("CopyRow", "documents_template_copies")]),
    *models(
        "engine",
        "ops_engine.store.definitions",
        [
            ("DefinitionRow", "engine_definitions"),
            ("DefinitionSummary", "engine_definitions"),
            ("DefinitionVersion", "engine_definitions"),
        ],
    ),
    *models(
        "engine",
        "ops_engine.store.runs",
        [("RunRow", "engine_runs"), ("ListedRun", "engine_runs"), ("RunStep", "engine_steps")],
    ),
]

NOT_COVERED = (
    "agents: ActivityEntry (a union of several tables, no single table to read it from)",
    "platform: claims and service replies (read from a token or a reply, not from a stored row)",
    "tools: app cards, module operation replies and built-in tool declarations (built from code and plugin answers)",
    "kb: item and search reply parts, source config build parts (replies built from rows the models above read)",
    "every reader outside the touched modules (files, models, calls, egress, secrets, graph runs) and the cases "
    "the services pass defaults to",
)


# --- tables and checks --------------------------------------------------------------------------------------------


def tables() -> dict[str, sa.Table]:
    """Every table the imported service modules define, by database name; the widest definition of a name wins."""
    found: dict[str, sa.Table] = {}
    for name, module in list(sys.modules.items()):
        if not name.startswith("ops_"):
            continue
        for value in list(vars(module).values()):
            held: object = value
            candidates: list[sa.Table] = []
            if isinstance(held, sa.Table):
                candidates = [cast("sa.Table", held)]
            elif isinstance(held, sa.MetaData):
                candidates = list(held.tables.values())
            for table in candidates:
                known = found.get(table.name)
                if known is None or len(table.c) > len(known.c):
                    found[table.name] = table
    return found


def model_check(model: type[BaseModel], table: sa.Table) -> tuple[list[sa.ColumnElement[Any]], Check]:
    """The columns of `table` that `model` names, and a check that validates a row of them with the model. A required
    field the table has no column for is derived by the query (a join, a count) and is not judged."""
    have = {c.name for c in table.c}
    keys: list[tuple[str, str]] = []
    derived: set[str] = set()
    for name, info in model.model_fields.items():
        column = next((n for n in (info.alias, name) if n and n in have), None)
        if column is None:
            derived.add(info.alias or name)
        else:
            keys.append((column, info.alias or name))
    if not keys:
        raise LookupError(f"{model.__name__} names no column of {table.name}")

    def check(row: Mapping[str, Any]) -> object:
        try:
            return model.model_validate({key: row[column] for column, key in keys})
        except ValidationError as e:
            kept = [x for x in e.errors() if not (x["type"] == MISSING and x["loc"] and str(x["loc"][0]) in derived)]
            if kept:
                raise Refused(sorted({str(x["loc"][0]) if x["loc"] else "(row)" for x in kept})) from None
            return None

    return [table.c[column] for column, _ in keys], check


class Refused(Exception):
    """A reader refused a row; `keys` names the keys that failed, never their values."""

    def __init__(self, keys: list[str]) -> None:
        super().__init__(", ".join(keys))
        self.keys = keys


_STORED = re.compile(r"^\S+: (?P<keys>.+) does not match the declared type$")


def refusal(e: Exception) -> list[str]:
    """The key names of a refusal. A `StoredShapeError` says them; any other error names only its type, since its
    message may quote a value."""
    if isinstance(e, Refused):
        return e.keys
    if type(e).__name__ == "StoredShapeError":
        found = _STORED.match(str(e))
        return [k.strip() for k in found["keys"].split(",")] if found else ["(document)"]
    return [f"(document: {type(e).__name__})"]


# --- running ------------------------------------------------------------------------------------------------------


def refuse_writes(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
    if not statement.lstrip().upper().startswith(ALLOWED):
        raise RuntimeError("check_stored_rows sends only SELECT; refused a statement")


async def visibility(conn: AsyncConnection) -> tuple[str, bool]:
    """The login's name and whether it sees every tenant's rows. PostgreSQL: a superuser or BYPASSRLS login does. On
    SQL Server the script cannot tell whether a security policy hides rows, so it says the rows are those visible."""
    if conn.dialect.name == "postgresql":
        row = (
            await conn.execute(
                sa.text("SELECT current_user, rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
        return str(row[0]), bool(row[1])
    return str((await conn.execute(sa.text("SELECT USER_NAME()"))).scalar_one()), False


async def run_reader(engine: AsyncEngine, reader: Reader, limit: int | None) -> Outcome:
    out = Outcome(reader.table)
    try:
        for name in (reader.home, *(m.partition(":")[0] for m in (reader.model,) if m and not m.startswith("@"))):
            load(name + ":")
        # A registry names its tables and row models on its class (`@module:Class.attr`).
        model_path = reader.model
        if reader.table.startswith("@"):
            out.table = load(reader.table[1:]).name
        if model_path and model_path.startswith("@"):
            model_path = model_path[1:]
        table = tables()[out.table]
        if model_path:
            columns, check = model_check(load(model_path), table)
        else:
            assert reader.build is not None
            check = reader.build()
            columns = [table.c[c] for c in reader.columns]
        shown = {c.name for c in columns}
        keys = list(table.primary_key.columns)
        extra = [c for c in keys if c.name not in shown]
        select = sa.select(*columns, *extra)
        if reader.only is not None:
            select = select.where(table.c[reader.only[0]] == reader.only[1])
            if reader.only[0] not in shown:
                select = select.add_columns(table.c[reader.only[0]])
        select = select.order_by(*keys)
        offset = 0
        async with engine.connect() as conn:
            await conn.begin()
            if conn.dialect.name == "postgresql":
                await conn.execute(sa.text("SET TRANSACTION READ ONLY"))
            while limit is None or offset < limit:
                size = BATCH if limit is None else min(BATCH, limit - offset)
                batch = (await conn.execute(select.limit(size).offset(offset))).mappings().all()
                for row in batch:
                    try:
                        check(dict(row))
                        out.read += 1
                    except Exception as e:
                        where = " ".join(f"{c.name}={row[c.name]}" for c in keys)
                        out.refused.append((where, ", ".join(refusal(e))))
                offset += len(batch)
                if len(batch) < size:
                    break
            await conn.rollback()
    except NotInVersion:
        out.absent = True
    except Exception as e:
        first = (str(e).splitlines() or [""])[0][:160]
        out.failure = f"{type(e).__name__}: {first}"
    return out


def open_engine(url: str) -> AsyncEngine:
    """The engine for `url`. The plain URL `fly postgres attach` prints is opened with the asyncpg driver and its
    `sslmode`; a SQLAlchemy URL is opened as given. An unreadable URL stops the run without quoting it, since it
    holds the password."""
    options: dict[str, Any] = {}
    mode = ssl_mode(url)
    if mode:
        options["connect_args"] = {"ssl": mode}
    target = asyncpg_url(url)
    try:
        make_url(target)
    except (sa.exc.ArgumentError, ValueError):
        sys.exit("OPS_DATABASE_URL is not a database URL (not shown: it holds the password)")
    return load("ops_store.database:open_database")(target, **options)


async def main_async(args: argparse.Namespace) -> int:
    chosen = [r for r in READERS if args.service in (None, r.service)]
    if args.list:
        for r in chosen:
            print(f"{r.service:10} {r.name}")
        return 0
    engine = open_engine(Settings().database_url)
    event.listen(engine.sync_engine, "before_cursor_execute", refuse_writes)
    problems = 0
    absent: list[str] = []
    read = refused = 0
    try:
        async with engine.connect() as conn:
            role, sees_all = await visibility(conn)
            await conn.rollback()
        dialect = make_url(Settings().database_url).get_backend_name()
        print(f"database: {dialect}, read as {role}; sees every tenant's rows: {'yes' if sees_all else 'no'}")
        for r in chosen:
            out = await run_reader(engine, r, args.limit)
            if out.absent:
                absent.append(r.name)
                print(f"{r.name}  {out.table or r.table}  not in this version")
                continue
            if out.failure is not None:
                problems += 1
                print(f"{r.name}  {out.table}  CANNOT RUN  {out.failure}")
                continue
            read += out.read
            refused += len(out.refused)
            print(f"{r.name}  {out.table}  read {out.read}  refused {len(out.refused)}")
            for where, key in out.refused[:NAMED]:
                print(f"  refused: {out.table} {where} key {key}")
            if len(out.refused) > NAMED:
                print(f"  ... {len(out.refused) - NAMED} more refused rows in {out.table}")
        if not sees_all:
            print(f"checked only rows visible to {role}")
            problems += 0 if args.visible_only else 1
    finally:
        await engine.dispose()
    if not args.service:
        print("not covered:")
        for line in NOT_COVERED:
            print(f"  {line}")
    print(f"stored rows: {read} read, {refused} refused, {len(absent)} readers not in this version")
    return 1 if refused or problems else 0


def self_test() -> int:
    """The checks refuse what they should: a stored config with a key of the wrong type, a row model missing a
    required value, and nothing else."""
    config = load("ops_platform.store.signin:PROVIDER_CONFIG")
    config({"tiles": True, "groups": {"source": None}})
    try:
        config({"tiles": "false"})
    except Exception as e:
        assert refusal(e) == ["tiles"], refusal(e)
    else:
        print("self-test: a config with tiles as a string was read")
        return 1

    class Row(BaseModel):
        id: str
        count: int
        joined: str

    table = sa.Table(
        "probe", sa.MetaData(), sa.Column("id", sa.String, primary_key=True), sa.Column("count", sa.Integer)
    )
    _, check = model_check(Row, table)
    check({"id": "a", "count": 1})
    try:
        check({"id": "a", "count": "x"})
    except Refused as e:
        assert e.keys == ["count"], e.keys
    else:
        print("self-test: a row with a text count was read")
        return 1
    print("self-test: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--service", choices=sorted({r.service for r in READERS}), help="only this service's readers")
    parser.add_argument("--limit", type=int, default=None, help="rows read per reader (default: all)")
    parser.add_argument("--visible-only", action="store_true", help="exit 0 although the login sees only some tenants")
    parser.add_argument("--list", action="store_true", help="list the readers and stop")
    parser.add_argument("--self-test", action="store_true", help="prove the checks refuse a bad value, then stop")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
