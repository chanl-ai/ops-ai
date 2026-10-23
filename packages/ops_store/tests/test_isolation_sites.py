"""Every place source code widens or sets the isolation context, by reason (c-409). A widening with no reason, a new
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
    "KEY_LOOKUP": {"services/platform-service/src/ops_platform/store/identity.py"},
    "INVITE_LOOKUP": {"services/platform-service/src/ops_platform/store/members.py"},
    "SIGNIN_LOCKOUT": {"services/platform-service/src/ops_platform/store/signin.py"},
    "RESET_LOOKUP": {"services/platform-service/src/ops_platform/store/signin.py"},
    "TESTS": {"services/agents-service/src/ops_agents/store/tenancy.py"},
    "SEED": {
        "services/agents-service/src/ops_agents/api/app.py",
        "services/agents-service/src/ops_agents/api/engine_seed.py",
    },
    "ENGINE_PASS": {"services/agents-service/src/ops_agents/api/worker.py"},
    "MEMORY_RETENTION": {"services/agents-service/src/ops_agents/api/memory_retention.py"},
    "MAIL_LISTENER": {
        "services/agents-service/src/ops_agents/api/email_trigger.py",
        "services/agents-service/src/ops_agents/store/mailboxes.py",
    },
    "CLAIM_THREAD": {"services/agents-service/src/ops_agents/store/graphs.py"},
    "RETENTION_TENANTS": {"services/agents-service/src/ops_agents/store/memories.py"},
    "CLAIM_WORK": {"packages/ops_engine/src/ops_engine/store/work.py"},
    "LIVE_WORKFLOWS": {"packages/ops_engine/src/ops_engine/store/definitions.py"},
    "SUITE": {"packages/ops_store/src/ops_store/conformance.py"},
    "STORAGE_TARGETS": {"services/files-service/src/ops_files/store/settings.py"},
    # c-507: kb's background processes, the dev demo seed and the start-up move between file stores.
    "MOVE_TENANTS": {"services/kb-service/src/ops_kb/store/knowledge.py"},
    "DEMO_SEED": {"services/kb-service/src/ops_kb/__main__.py"},
    "MOVE_FILES": {"services/kb-service/src/ops_kb/__main__.py"},
    "RELAY": {"packages/ops_store/src/ops_store/outbox.py"},
    # c-516: heartbeats describe a process, which serves every tenant; the Background page reads every team's jobs.
    "HEARTBEAT": {"packages/ops_store/src/ops_store/background.py"},
    "BACKGROUND_PAGE": {"services/agents-service/src/ops_agents/store/background.py"},
    "RECOVER_PENDING": {
        "services/documents-service/src/ops_documents/store/document_types.py",
        "services/documents-service/src/ops_documents/store/extractions.py",
    },
}
# `isolation.enter` / `enter_caller` / `scope`: who sets a team scope that no verified principal set for them.
ENTRIES: dict[str, set[str]] = {
    "enter_caller": {"packages/ops_identity/src/ops_identity/fastapi.py"},
    "enter": {
        "services/agents-service/src/ops_agents/api/routers/widget.py",
        "services/agents-service/src/ops_agents/api/worker.py",
    },
    "scope": {
        "packages/ops_store/src/ops_store/outbox.py",
        "services/documents-service/src/ops_documents/document_types.py",
        "services/documents-service/src/ops_documents/extraction.py",
        "services/agents-service/src/ops_agents/api/publish_reviews.py",
        "services/agents-service/src/ops_agents/api/tenant_tasks.py",
        "services/platform-service/src/ops_platform/store/tenancy.py",
    },
}
# Names a service once used to set its own context. `set_acting_team` is c-407's filter; kb-service still sets it for
# a service caller (c-416).
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
