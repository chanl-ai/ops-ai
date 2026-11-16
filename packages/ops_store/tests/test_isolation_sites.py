"""Every place source code widens or sets the isolation context, by reason. A widening with no reason, a new
call site, or a service setting its own tenant or team fails here naming the file; each list only changes with the
card that changes the call. Tests are not scanned: they act for whichever tenant they set up.

platform-service names the tenant per transaction (it issues the tokens), so its one `scope` entry is its binding.

Two more lists, one file per service under `isolation_sites/`, each row `<count> <kind> <file>`:

  raw     a transaction opened on the engine itself (`engine.begin()`, `engine.connect()`, the same on a `db` handle)
          instead of through `Store.tx()`, so it is a second connection beside the request's and carries no caller
  caught  a handler that catches a database error and carries on with no savepoint (`Store.attempt`) around the
          statement; on the request's one transaction PostgreSQL refuses every statement after the failed one

A row may only fall: a new site fails here naming its line, and a site that is gone fails until its row is lowered."""

from __future__ import annotations

import ast
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCES = sorted(p for p in (*ROOT.glob("packages/*/src"), *ROOT.glob("services/*/src")) if p.is_dir())
MECHANISM = {"packages/ops_store/src/ops_store/isolation.py", "packages/ops_store/src/ops_store/dialect.py"}
BASELINES = Path(__file__).parent / "isolation_sites"
# The names a service gives its database handle; a transaction opened on one of them is a raw site.
HANDLES = {"engine", "db", "database"}
DB_ERRORS = {
    "DataError",
    "DBAPIError",
    "IntegrityError",
    "InterfaceError",
    "OperationalError",
    "ProgrammingError",
    "SQLAlchemyError",
    "StatementError",
}

# Reason (as written at the call) -> the files that widen for it. `reason` is a binding that passes its caller's on.
WIDENINGS: dict[str, set[str]] = {
    "reason": {
        "packages/ops_store/src/ops_store/store.py",
        "services/agents-service/src/ops_agents/store/engine.py",
        "services/agents-service/src/ops_agents/store/tenancy.py",
        "services/platform-service/src/ops_platform/store/tenancy.py",
    },
    "SIGNIN_LOOKUP": {
        "services/platform-service/src/ops_platform/store/identity.py",
        "services/platform-service/src/ops_platform/store/signin.py",
    },
    "SESSION_LOOKUP": {"services/platform-service/src/ops_platform/store/identity.py"},
    "WIDGET_LOOKUP": {"services/agents-service/src/ops_agents/api/routers/widget.py"},
    # The workflow worker reads every tenant's pending batch rows, then starts each in its own tenant and team.
    "BATCH_START": {"services/agents-service/src/ops_agents/store/batches.py"},
    "KEY_LOOKUP": {"services/platform-service/src/ops_platform/store/identity.py"},
    "INVITE_LOOKUP": {"services/platform-service/src/ops_platform/store/members.py"},
    "SIGNIN_LOCKOUT": {"services/platform-service/src/ops_platform/store/signin.py"},
    # The daily certificate watch lists every SAML provider of an open workspace (platform_signin_watch).
    "SIGNIN_WATCH": {"services/platform-service/src/ops_platform/store/signin.py"},
    "RESET_LOOKUP": {"services/platform-service/src/ops_platform/store/signin.py"},
    "PURGE_LOOKUP": {"services/platform-service/src/ops_platform/store/lifecycle.py"},
    "TESTS": {"services/agents-service/src/ops_agents/store/tenancy.py"},
    "SEED": {
        "services/agents-service/src/ops_agents/api/app.py",
        "services/agents-service/src/ops_agents/api/engine_seed.py",
        # The dev seed writes every team's connections into the dev tenant.
        "services/tools-service/src/ops_tools/modules/seed.py",
    },
    "ENGINE_PASS": {"services/agents-service/src/ops_agents/api/worker.py"},
    "MEMORY_RETENTION": {"services/agents-service/src/ops_agents/api/memory_retention.py"},
    "MAIL_LISTENER": {
        "services/agents-service/src/ops_agents/api/email_trigger.py",
        "services/agents-service/src/ops_agents/store/mailboxes.py",
    },
    "CLAIM_THREAD": {"services/agents-service/src/ops_agents/store/graphs.py"},
    "RETENTION_TENANTS": {"services/agents-service/src/ops_agents/store/memories.py"},
    "ASSISTANT_TEAMS": {"services/agents-service/src/ops_agents/store/team_defaults.py"},
    "ASSISTANT_CATCH_UP": {"services/agents-service/src/ops_agents/api/ops_tools.py"},
    "CLAIM_WORK": {"packages/ops_engine/src/ops_engine/store/work.py"},
    "LIVE_WORKFLOWS": {"packages/ops_engine/src/ops_engine/store/definitions.py"},
    # The run reconciler reads every tenant's unfinished runs, then marks each in its own tenant.
    "RECONCILE_RUNS": {"packages/ops_engine/src/ops_engine/store/reconciler.py"},
    "RUN_RECONCILER": {"services/agents-service/src/ops_agents/api/sweeper.py"},
    "SUITE": {"packages/ops_store/src/ops_store/conformance.py"},
    "STORAGE_TARGETS": {"services/files-service/src/ops_files/store/settings.py"},
    # The retention process lists every tenant's released snapshots past their date, then deletes each in its team.
    "RETENTION_DUE": {"services/files-service/src/ops_files/store/files.py"},
    # Kb's background processes, the dev demo seed and the start-up move between file stores.
    "MOVE_TENANTS": {"services/kb-service/src/ops_kb/store/knowledge.py"},
    "DEMO_SEED": {"services/kb-service/src/ops_kb/__main__.py"},
    "MOVE_FILES": {"services/kb-service/src/ops_kb/__main__.py"},
    # The knowledge schedule finds each tenant's due tool sources, then syncs each in its own team's scope.
    "FIND_DUE": {"services/kb-service/src/ops_kb/schedule.py"},
    # The schedule finds each tenant's items waiting on a reading, then settles each in its own team.
    "FIND_READING": {"services/kb-service/src/ops_kb/schedule.py"},
    # And ends each tenant's runs a stopped process left marked running.
    "FIND_STALE": {"services/kb-service/src/ops_kb/schedule.py"},
    "PURGE_WITHDRAWN": {"services/kb-service/src/ops_kb/schedule.py"},
    "FIND_PENDING": {"services/kb-service/src/ops_kb/embedding.py"},
    "RELAY": {"packages/ops_store/src/ops_store/outbox.py"},
    # Heartbeats describe a process, which serves every tenant; the Background page reads every team's jobs.
    "HEARTBEAT": {"packages/ops_store/src/ops_store/background.py"},
    "BACKGROUND_PAGE": {"services/agents-service/src/ops_agents/store/background.py"},
    "RECOVER_PENDING": {
        "services/documents-service/src/ops_documents/store/document_types.py",
        "services/documents-service/src/ops_documents/store/extractions.py",
        "services/documents-service/src/ops_documents/store/readings.py",
    },
}
# `isolation.enter` / `enter_caller` / `scope`: who sets a team scope that no verified principal set for them.
ENTRIES: dict[str, set[str]] = {
    "enter_caller": {
        "packages/ops_identity/src/ops_identity/fastapi.py",
        # The MCP adapter is an ASGI app, so it enters its verified caller itself.
        "services/tools-service/src/ops_tools/mcp_server.py",
    },
    "enter": {
        # A hosted form's link enters the tenant and team its signed token names; a members-only form, each of
        # the signed-in person's own teams in turn.
        "services/agents-service/src/ops_agents/api/routers/forms.py",
        "services/agents-service/src/ops_agents/api/routers/run_resume.py",
        "services/agents-service/src/ops_agents/api/routers/widget.py",
        "services/agents-service/src/ops_agents/api/worker.py",
    },
    "scope": {
        "services/agents-service/src/ops_agents/api/batches.py",
        # The apps a team has turned off are read in the team the call names.
        "services/tools-service/src/ops_tools/app.py",
        # A checkpointer built for one tenant and team (tests, tools) scopes each transaction to them, never to a
        # config's; the Runtime's checkpointer acts in the caller's context.
        "packages/ops_checkpointer/src/ops_checkpointer/saver.py",
        "packages/ops_store/src/ops_store/outbox.py",
        "services/documents-service/src/ops_documents/document_types.py",
        "services/documents-service/src/ops_documents/extraction.py",
        # The retention process deletes each released snapshot as its own tenant and team.
        "services/files-service/src/ops_files/tenant_files.py",
        # A queued reading is read in the team that asked for it.
        "services/documents-service/src/ops_documents/readings.py",
        # A reading event settles the items of the one team its service token names.
        "services/kb-service/src/ops_kb/app.py",
        "services/agents-service/src/ops_agents/api/publish_reviews.py",
        "services/agents-service/src/ops_agents/api/tenant_tasks.py",
        # A chat link opened while acting in another team looks in each of the reader's own teams in turn.
        "services/agents-service/src/ops_agents/api/routers/chat.py",
        # A run, and a write to a thread's state outside one, act as the thread's team, so every checkpoint is
        # in exactly one team whoever started the run.
        "services/agents-service/src/ops_agents/api/runs.py",
        "services/platform-service/src/ops_platform/store/tenancy.py",
        "services/kb-service/src/ops_kb/schedule.py",
        # A Security admin's request on another team's secrets, after the rights check, acts in that team.
        "services/tools-service/src/ops_tools/secrets/routes.py",
        # The start-up move of sign-in header keys acts on each module in the module's own team.
        "services/tools-service/src/ops_tools/header_keys.py",
        # An MCP link is read and changed in the team its caller names, the MCP door included, which has no request
        # team of its own.
        "services/tools-service/src/ops_tools/store/mcp_links.py",
        # The sign-in keep-alive refreshes each team's sign-ins in that team's own scope.
        "services/tools-service/src/ops_tools/connections/keepalive.py",
        # A model call reads its tenant's provider key, or the deployment's when it names none.
        "services/models-service/src/ops_models/provider_keys.py",
        # A per-tenant model key's call spends from the share of the tenant it names (X-Tenant-Id).
        "services/models-service/src/ops_models/app.py",
    },
}
# Names a service once used to set its own context. `set_acting_team` is the filter; kb-service still sets it for
# a service caller.
REFUSED = {"set_tenant", "set_team", "tenant_scope", "enter_tenant"}
ACTING_TEAM = {"services/kb-service/src/ops_kb/app.py"}


def _calls() -> list[tuple[str, ast.Call, str]]:
    out: list[tuple[str, ast.Call, str]] = []
    for src in SOURCES:
        for path in src.rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel in MECHANISM:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                    out.append((rel, node, name))
    return out


def _reason(call: ast.Call) -> str | None:
    for kw in call.keywords:
        if kw.arg == "reason":
            return ast.unparse(kw.value)
    args = [a for a in call.args if not isinstance(a, ast.Starred)]
    if not args:
        return None
    arg = args[-1]
    # `isolation.tenant_wide(REASON, tenant_id=...)` and `tx.system_tx(REASON)` take it last; `system_tx(engine,
    # REASON)` too. A constant's attribute form (`tenancy.SEED`) is listed by its last name.
    return arg.attr if isinstance(arg, ast.Attribute) else ast.unparse(arg)


def test_every_widening_names_a_listed_reason_at_a_listed_site() -> None:
    found: dict[str, set[str]] = defaultdict(set)
    unnamed: list[str] = []
    for rel, call, name in _calls():
        if name not in {"tenant_wide", "system_tx"}:
            continue
        reason = _reason(call)
        if reason is None or reason.startswith(("'", '"', "f'", 'f"')):
            unnamed.append(f"{rel}:{call.lineno} {name}({reason or ''})")
            continue
        found[reason].add(rel)
    assert unnamed == [], "a widening names no reason constant:\n" + "\n".join(unnamed)
    assert dict(found) == WIDENINGS


def test_only_the_listed_places_set_a_scope_no_principal_set() -> None:
    found: dict[str, set[str]] = defaultdict(set)
    for rel, call, name in _calls():
        f = call.func
        if (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == "isolation"
            and name in ENTRIES
        ):
            found[name].add(rel)
    assert dict(found) == ENTRIES


def test_no_service_sets_its_own_tenant_or_team() -> None:
    refused = sorted(f"{rel}:{call.lineno} {name}" for rel, call, name in _calls() if name in REFUSED)
    assert refused == []
    acting = {rel for rel, _call, name in _calls() if name == "set_acting_team"}
    assert acting == ACTING_TEAM


def _handle(node: ast.expr) -> str | None:
    name = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else None
    return name.lstrip("_") if name else None


def _names(node: ast.AST) -> set[str]:
    return {
        n.attr if isinstance(n, ast.Attribute) else n.id
        for n in ast.walk(node)
        if isinstance(n, ast.Attribute | ast.Name)
    }


def _in_savepoint(attempt: ast.Try) -> bool:
    """Whether the guarded statements run inside `attempt(...)`, which rolls back to its savepoint first."""
    return any(
        isinstance(item.context_expr, ast.Call) and _handle(item.context_expr.func) == "attempt"
        for stmt in attempt.body
        for node in ast.walk(stmt)
        if isinstance(node, ast.With | ast.AsyncWith)
        for item in node.items
    )


# Calls that send a statement; a catch around one is a catch around the database.
STATEMENTS = {"execute", "executemany", "scalar", "scalars", "commit", "flush"}
BROAD = {"Exception", "BaseException"}


def _sends_statement(nodes: list[ast.stmt]) -> bool:
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in STATEMENTS
        for stmt in nodes
        for n in ast.walk(stmt)
    )


def site_findings(source: str) -> list[tuple[int, str]]:
    """(line, kind) for each raw transaction, each caught database error and each broad catch or `suppress` around a
    statement, with no savepoint, in one file."""
    out: set[tuple[int, str]] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"begin", "connect"}
            and _handle(node.func.value) in HANDLES
        ):
            out.add((node.lineno, "raw"))
        # Whatever the handle is called (`self.registry`, `get_engine()`), a transaction opened by `async with`
        # outside ops_store is a second connection beside the request's.
        if isinstance(node, ast.AsyncWith):
            out |= {
                (item.context_expr.lineno, "raw")
                for item in node.items
                if isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr in {"begin", "connect"}
            }
        if isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                call = item.context_expr
                if not (isinstance(call, ast.Call) and _handle(call.func) == "suppress"):
                    continue
                caught = {n for arg in call.args for n in _names(arg)}
                if caught & DB_ERRORS or (caught & BROAD and _sends_statement(node.body)):
                    out.add((node.lineno, "suppressed"))
        if isinstance(node, ast.Try) and not _in_savepoint(node):
            for h in node.handlers:
                # A handler whose last statement raises does not carry on; one that retries or answers does.
                if isinstance(h.body[-1], ast.Raise):
                    continue
                caught = _names(h.type) if h.type is not None else set()
                if caught & DB_ERRORS:
                    out.add((h.lineno, "caught"))
                elif (h.type is None or caught & BROAD) and _sends_statement(node.body):
                    out.add((h.lineno, "broad"))
    return sorted(out)


def _found() -> tuple[dict[str, Counter[str]], dict[str, list[int]]]:
    """Counts by service and row key, and the lines behind each key."""
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    lines: dict[str, list[int]] = defaultdict(list)
    for src in sorted([*ROOT.glob("services/*/src"), *ROOT.glob("packages/*/src")]):
        if src.parent.name == "ops_store":
            continue
        for path in sorted(src.rglob("*.py")):
            for line, kind in site_findings(path.read_text()):
                key = f"{kind} {path.relative_to(ROOT).as_posix()}"
                counts[src.parent.name][key] += 1
                lines[key].append(line)
    return counts, lines


def _listed(service: str) -> Counter[str]:
    path = BASELINES / f"{service}.txt"
    rows = (
        [r.split(" ", 1) for r in path.read_text().splitlines() if r and not r.startswith("#")] if path.exists() else []
    )
    return Counter({key: int(n) for n, key in rows})


def test_raw_transactions_and_caught_errors_are_only_the_listed_ones() -> None:
    counts, lines = _found()
    problems: list[str] = []
    for service in sorted({*counts, *(p.stem for p in BASELINES.glob("*.txt"))}):
        listed, now = _listed(service), counts.get(service, Counter())
        for key in sorted({*listed, *now}):
            kind, rel = key.split(" ", 1)
            where = ", ".join(f"{rel}:{n}" for n in lines.get(key, []))
            if now[key] > listed[key]:
                fix = "use Store.tx()" if kind == "raw" else "run the statement inside Store.attempt(conn)"
                problems.append(f"{service}: {kind} {now[key]} > {listed[key]} at {where}; {fix}")
            elif now[key] < listed[key]:
                problems.append(f"{service}: {key} fell to {now[key]}; lower its row in isolation_sites/{service}.txt")
    assert problems == [], "\n".join(problems)


def test_the_site_scan_finds_each_kind_and_passes_the_savepoint_form() -> None:
    planted = """
async def raw(self):
    async with self.engine.begin() as c: ...
    async with self._db.connect() as c: ...

async def caught(self, conn):
    try:
        await conn.execute(q)
    except IntegrityError:
        return False

async def retried(self, conn):
    for attempt in range(3):
        try:
            await conn.execute(q)
        except sa.exc.OperationalError:
            if attempt == 2:
                raise

async def passed_on(self, conn):
    try:
        await conn.execute(q)
    except IntegrityError as e:
        raise Conflict("taken") from e

async def savepoint(self, conn):
    try:
        async with self.attempt(conn):
            await conn.execute(q)
    except IntegrityError:
        return False
    async with self.tx() as c: ...
"""
    assert site_findings(planted) == [(3, "raw"), (4, "raw"), (9, "caught"), (16, "caught")]


def test_the_site_scan_finds_a_transaction_on_any_handle_and_a_broad_catch_around_a_statement() -> None:
    planted = """
async def registry(self):
    async with self.registry.begin() as c: ...
    async with get_engine().connect() as c: ...
    async with self.engine.begin() as c: ...

async def broad(self, conn):
    try:
        await conn.execute(q)
    except Exception:
        return False

async def bare(self, conn):
    try:
        await conn.execute(q)
    except:
        pass

async def quiet(self, conn):
    with suppress(IntegrityError):
        await conn.execute(q)

async def quiet_broad(self, conn):
    with contextlib.suppress(Exception):
        await conn.execute(q)

async def quiet_other(self):
    with suppress(KeyError):
        await notify()

async def no_statement(self):
    try:
        await notify()
    except Exception:
        pass

async def passed_on(self, conn):
    try:
        await conn.execute(q)
    except Exception as e:
        raise Wrapped() from e

async def savepoint(self, conn):
    try:
        async with self.attempt(conn):
            await conn.execute(q)
    except Exception:
        return False
"""
    assert site_findings(planted) == [
        (3, "raw"),
        (4, "raw"),
        (5, "raw"),
        (10, "broad"),
        (16, "broad"),
        (20, "suppressed"),
        (24, "suppressed"),
    ]


def test_a_baseline_only_falls_in_the_history() -> None:
    """A row raised, or a file added, in a commit with no `Standards-exception:` trailer: the working tree alone
    cannot show it, since the baseline and the code are changed together."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import baseline_history  # noqa: PLC0415

    assert (
        baseline_history.problems(
            ROOT, "fe46c615f0a2e3fc501853005e71564d2fc5edd1", ["packages/ops_store/tests/isolation_sites"]
        )
        == []
    )
