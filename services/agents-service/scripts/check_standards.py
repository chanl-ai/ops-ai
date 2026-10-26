"""Standards spec 17 section 8 enforces. Exits non-zero with file:line for each breach.

1 layers import one direction · 3 fixtures only under tests/fixtures · 3b source names no tests/ path · 4 env read
only in ops_service_kit/settings.py · 5 every route authenticated · 6 no print or logging.getLogger in packages. 1b
ops_engine imports nothing from ops_agents (docs/architecture/workflow-runner.md section 2). Database drivers outside a
store are the drivers-only-in-stores contract in .importlinter (`uv run lint-imports`).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

from fastapi.routing import APIRoute, iter_route_contexts

from ops_agents.api.app import create_app
from ops_agents.api.auth import principal, service_principal
from ops_agents.api.routers.run_resume import resume_caller
from ops_agents.api.routers.widget import mint_key_caller, widget_caller
from ops_identity import current_caller, current_principal, current_service, current_tenant_caller
from ops_service_kit.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
# Source trees of the Python workspace: reusable libraries and the services built from them.
SRC_ROOTS = sorted([*ROOT.glob("packages/*/src"), *ROOT.glob("services/*-service/src")])
ORDER = [
    "ops_contracts",
    "ops_pii",
    "ops_policy",
    "ops_service_kit",
    # Below ops_identity, which enters each request's isolation context (ops_store.isolation, c-409).
    "ops_store",
    "ops_identity",
    "ops_access",
    "ops_metering",
    "ops_storage",
    "ops_ingest",
    "ops_extract",
    "ops_files",
    "ops_files_client",
    "ops_documents_client",
    "ops_documents",
    "ops_email",
    "ops_signin",
    # Code tools' runner (c-531): the kit and identity below it, reached by tools-service over HTTP only.
    "ops_runner",
    "ops_agent_kernel",
    "ops_checkpointer",
    # The workflow runner sits below every ops_agents layer, so rule 1 refuses any import of ops_agents from it.
    "ops_engine",
    "ops_agents.activities",
    "ops_agents.graphs",
    "ops_agents.store",
    "ops_tools",
    "ops_models",
    "ops_kb",
    "ops_platform",
    "ops_agents.api",
]
KIT = ROOT / "packages" / "ops_service_kit" / "src" / "ops_service_kit"
SETTINGS = KIT / "settings.py"
LOGGING = KIT / "logging.py"
# /widget/v1.js answers 410 Gone (retired by c-224); /embed/v1.js is the loader a page loads: no key, no data.
PUBLIC_ROUTES = {
    "/health",
    "/health/background",
    "/healthz",
    "/readyz",
    "/v1/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/widget/v1.js",
    "/embed/v1.js",
    # The embed app's pre-session read: agent name, pause and the origins for frame-ancestors (c-131).
    "/v1/widget/{deployment_id}/config",
}


def sources() -> list[Path]:
    return sorted(p for src in SRC_ROOTS for p in src.rglob("*.py"))


# ops_agents holds three layers of its own; the others are one layer per top-level module.
SPLIT = {"ops_agents"}


def layer_of(module: str) -> str:
    """Layer of a dotted module: `ops_agents.api.app` -> `ops_agents.api`; `ops_tools.x` -> `ops_tools`."""
    parts = module.split(".")
    return ".".join(parts[:2]) if parts[0] in SPLIT and len(parts) > 1 else parts[0]


def package_of(path: Path) -> str:
    """The layer a file belongs to, from its path under `src/`."""
    parts = path.relative_to(ROOT).parts
    i = parts.index("src") + 1
    if parts[i] in SPLIT and parts[i + 1].endswith(".py"):
        # A file at the top of a split module (its __init__) belongs to its outermost layer.
        return max((name for name in ORDER if name.startswith(f"{parts[i]}.")), key=ORDER.index)
    return layer_of(".".join(parts[i : i + 2]))


def check_layers(path: Path, tree: ast.AST, out: list[str]) -> None:
    if package_of(path) not in ORDER:
        out.append(f"{path.relative_to(ROOT)} rule 1: {package_of(path)} is not in ORDER; place it in the layer order")
        return
    own = ORDER.index(package_of(path))
    for node in ast.walk(tree):
        names = (
            [a.name for a in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
            if isinstance(node, ast.ImportFrom) and node.level == 0
            else []
        )
        for name in names:
            if package_of(path) == "ops_engine" and name.split(".")[0] == "ops_agents":
                where = f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', 0)}"
                out.append(f"{where} rule 1b: ops_engine imports {name}; reach agents-service through a port")
                continue
            top = layer_of(name)
            if top in ORDER and ORDER.index(top) > own:
                where = f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', 0)}"
                out.append(f"{where} rule 1: {package_of(path)} imports {top}, a later layer")


def check_env(path: Path, tree: ast.AST, out: list[str]) -> None:
    if path == SETTINGS:
        return
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in {"environ", "getenv"}
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        ):
            out.append(
                f"{path.relative_to(ROOT)}:{node.lineno} rule 4: environment read outside ops_service_kit/settings.py"
            )
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("dotenv"):
            out.append(f"{path.relative_to(ROOT)}:{node.lineno} rule 4: dotenv import")


def check_logging(path: Path, tree: ast.AST, out: list[str]) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            out.append(f"{path.relative_to(ROOT)}:{node.lineno} rule 6: print in package code")
        if path != LOGGING and isinstance(node, ast.Attribute) and node.attr == "getLogger":
            out.append(
                f"{path.relative_to(ROOT)}:{node.lineno} rule 6: logging.getLogger outside ops_service_kit.logging"
            )


def check_fixtures(out: list[str]) -> None:
    for p in (f for src in SRC_ROOTS for f in src.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix in {".json", ".yaml", ".yml", ".eml"}:
            out.append(f"{p.relative_to(ROOT)} rule 3: data file in source code; fixtures live in tests/fixtures/")
        if p.suffix == ".py":
            for node in ast.walk(ast.parse(p.read_text())):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 2048:
                    out.append(f"{p.relative_to(ROOT)}:{node.lineno} rule 3: string literal over 2 KB")
    for p in (f for top in ("packages", "services", "deploy") for f in (ROOT / top).rglob(".env*")):
        if ".venv" not in p.parts:
            out.append(f"{p.relative_to(ROOT)} rule 4: .env file (read settings from the environment)")


TESTS_PATH = re.compile(r"(^|/)tests(/|$)")


def check_tests_paths(path: Path, tree: ast.AST, out: list[str]) -> None:
    """Rule 3b: a running service reads its own seed/ folder, never a tests/ path, so a test change cannot change what
    the product shows. Docstrings may mention tests; a string the code uses may not name one."""
    docs = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    # A bare "tests" is a path only as a segment joined with `/` (ROOT / "tests" / ...); as a dict key it is a name.
    segments = {
        id(side)
        for n in ast.walk(tree)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)
        for side in (n.left, n.right)
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or id(node) in docs:
            continue
        if ("/" in node.value and TESTS_PATH.search(node.value)) or (node.value == "tests" and id(node) in segments):
            out.append(
                f"{path.relative_to(ROOT)}:{node.lineno} rule 3b: names a tests/ path; read the service's seed/ folder"
            )


def check_routes(out: list[str]) -> int:
    """Returns how many routes it checked, so a check that silently sees none fails instead of passing."""
    app = create_app(Settings(database_url="sqlite+aiosqlite://"))

    def deps(dependant: object) -> set[object]:
        found: set[object] = set()
        stack = [dependant]
        while stack:
            d = stack.pop()
            for sub in getattr(d, "dependencies", []):
                found.add(sub.call)
                stack.append(sub)
        return found

    checked = 0
    # Included routers are nested in FastAPI 0.143; iter_route_contexts flattens them with their effective paths.
    for ctx in iter_route_contexts(app.routes):
        route = ctx.original_route
        if not isinstance(route, APIRoute) or (ctx.path or route.path) in PUBLIC_ROUTES:
            continue
        checked += 1
        # A user route depends on principal; an internal route (a scheduler's timer fire) on service_principal; a widget
        # page route on widget_caller (the X-Widget-Session the page was minted, c-117); the bank server's mint on
        # mint_key_caller (the deployment's mint key, c-131). A route a person or a service may call (c-180) reaches
        # ops_identity's current_caller, and a service-only one its current_service, through whatever wraps them; one a
        # person or any service of the tenant may call, whether or not its token names a team, current_tenant_caller.
        # An outside system resuming a parked workflow step holds that step's signed token, resume_caller (c-525).
        authenticated = {principal, service_principal, widget_caller, mint_key_caller, resume_caller}
        identity = {current_caller, current_principal, current_service, current_tenant_caller}
        if not deps(route.dependant) & (authenticated | identity):
            out.append(f"route {sorted(route.methods or set())} {ctx.path or route.path} rule 5: no auth dependency")
    return checked


def main() -> int:
    out: list[str] = []
    for path in sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        check_layers(path, tree, out)
        check_env(path, tree, out)
        check_logging(path, tree, out)
        check_tests_paths(path, tree, out)
    check_fixtures(out)
    if check_routes(out) == 0:
        out.append("rule 5: no authenticated routes were found to check")
    for line in out:
        sys.stderr.write(line + "\n")
    sys.stdout.write(f"check_standards: {len(sources())} files, {len(out)} problems\n")
    return 1 if out else 0


if __name__ == "__main__":
    raise SystemExit(main())
