"""Every place source code widens or sets the isolation context, by reason. A widening with no reason, a new
call site, or a service setting its own tenant or team fails here naming the file; each list only changes with the
card that changes the call. Tests are not scanned: they act for whichever tenant they set up.

platform-service names the tenant per transaction (it issues the tokens), so its one `scope` entry is its binding."""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCES = sorted(p for p in (*ROOT.glob("packages/*/src"), *ROOT.glob("services/*/src")) if p.is_dir())
MECHANISM = {"packages/ops_store/src/ops_store/isolation.py", "packages/ops_store/src/ops_store/dialect.py"}

# Reason (as written at the call) -> the files that widen for it. `reason` is a binding that passes its caller's on.
WIDENINGS: dict[str, set[str]] = {
    "reason": {
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
    # Kb's background processes, the dev demo seed and the start-up move between file stores.
    "MOVE_TENANTS": {"services/kb-service/src/ops_kb/store/knowledge.py"},
    "DEMO_SEED": {"services/kb-service/src/ops_kb/__main__.py"},
    "MOVE_FILES": {"services/kb-service/src/ops_kb/__main__.py"},
    # The knowledge schedule finds each tenant's due tool sources, then syncs each in its own team's scope.
    "FIND_DUE": {"services/kb-service/src/ops_kb/schedule.py"},
    # It also finds each tenant's items waiting for a file's reading, then asks again in each item's team.
    "FIND_READING": {"services/kb-service/src/ops_kb/schedule.py"},
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
    "enter_caller": {"packages/ops_identity/src/ops_identity/fastapi.py"},
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
        # A checkpointer built for one tenant and team (tests, tools) scopes each transaction to them, never to a
        # config's; the Runtime's checkpointer acts in the caller's context.
        "packages/ops_checkpointer/src/ops_checkpointer/saver.py",
        "packages/ops_store/src/ops_store/outbox.py",
        "services/documents-service/src/ops_documents/document_types.py",
        "services/documents-service/src/ops_documents/extraction.py",
        # A queued reading resumed after a restart reads the file as the team that asked for it.
        "services/documents-service/src/ops_documents/readings.py",
        # A service event (reading.finished) settles the items of the team its token names.
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
