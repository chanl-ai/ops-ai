"""Every route that writes asks `ops_access.can` (c-148). The routes are read from the code, so a new POST, PUT, PATCH
or DELETE route that decides with its own role check, or with none, fails here with its file and name.

A route reaches `can` when its handler, or a function it calls, calls `can` imported from `ops_access`. Calls are
resolved the way Python resolves them: a bare name to the module's own function or to what it imported, and
`module.function` through an imported `ops_agents` module. A call that cannot be resolved (a method on an object)
counts for nothing, so two functions sharing a name in different modules never vouch for each other.

EXEMPT names each route that legitimately asks no permission, with the reason; an entry whose route is gone fails too,
so the list cannot outlive what it excuses."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parents[2] / "src"
WRITES = {"post", "put", "patch", "delete"}
EXEMPT = {
    ("ops_agents.api.routers.step_up", "step_up"): "re-checks the caller's own password for their own session",
    ("ops_agents.api.routers.step_up", "sso_step_up"): "the same for a single sign-on session",
    ("ops_agents.api.routers.engine", "validate_definition"): "checks a posted definition and stores nothing",
    ("ops_agents.api.routers.widget", "server_session"): "authenticated by the deployment's mint key, not a principal",
    ("ops_agents.api.routers.run_resume", "resume_step"): (
        "authenticated by the step's own resume token, bound to its run, step, pass and team (c-525)"
    ),
    ("ops_agents.api.routers.forms", "submit_public"): "authenticated by the form's signed link token (c-535)",
    ("ops_agents.api.routers.forms", "upload_public"): "authenticated by the form's signed link token (c-535)",
    ("ops_agents.api.routers.forms", "submit_member"): (
        "membership of the form's team is the check: a members-only form is the team's own start form (c-535, E47)"
    ),
    ("ops_agents.api.routers.service_events", "emit_event"): (
        "a service token's events:emit scope, capped per service by Settings.service_scopes (c-258); no person calls it"
    ),
}
Fn = tuple[str, str]


def _module(path: Path) -> str:
    parts = list(path.relative_to(SRC).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _absolute(module: str, node: ast.ImportFrom, is_package: bool) -> str:
    if not node.level:
        return node.module or ""
    base = module.split(".")
    base = base if is_package else base[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _scan() -> tuple[dict[Fn, set[Fn]], list[tuple[Fn, str]]]:
    """Each function to the functions it calls (resolved), and every write route with its method. ("ops_access",
    "can") stands for the check itself."""
    files = {_module(p): p for p in sorted((SRC / "ops_agents").rglob("*.py"))}
    edges: dict[Fn, set[Fn]] = {}
    routes: list[tuple[Fn, str]] = []
    for module, path in files.items():
        tree = ast.parse(path.read_text())
        own = {n.name for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
        names: dict[str, Fn] = {}
        modules: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                source = _absolute(module, node, path.name == "__init__.py")
                for a in node.names:
                    if f"{source}.{a.name}" in files:
                        modules[a.asname or a.name] = f"{source}.{a.name}"
                    else:
                        names[a.asname or a.name] = (source, a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    modules[a.asname or a.name] = a.name
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            fn = (module, node.name)
            out = edges.setdefault(fn, set())
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                f = sub.func
                if isinstance(f, ast.Name):
                    out.add((module, f.id) if f.id in own else names.get(f.id, ("", "")))
                elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in modules:
                    out.add((modules[f.value.id], f.attr))
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in WRITES:
                    routes.append((fn, d.func.attr.upper()))
    return edges, routes


def _reaches_can(fn: Fn, edges: dict[Fn, set[Fn]], seen: set[Fn]) -> bool:
    if fn in seen:
        return False
    seen.add(fn)
    called = edges.get(fn, set())
    return ("ops_access", "can") in called or any(_reaches_can(n, edges, seen) for n in called)


def test_every_write_route_asks_can() -> None:
    edges, routes = _scan()
    assert len(routes) > 50
    missing = [
        f"{fn[0]}.{fn[1]} {method}" for fn, method in routes if fn not in EXEMPT and not _reaches_can(fn, edges, set())
    ]
    assert missing == []


def test_every_exemption_names_a_live_write_route() -> None:
    _, routes = _scan()
    assert set(EXEMPT) <= {fn for fn, _ in routes}
