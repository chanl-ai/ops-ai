"""Standards spec 17 section 8 enforces. Exits non-zero with file:line for each breach.

1 layers import one direction · 3 fixtures only under tests/fixtures · 4 env read only in ops_service_kit/settings.py ·
5 every route authenticated · 6 no print or logging.getLogger in packages · 15 database drivers (sqlalchemy,
asyncpg) imported only in a store package or module, ops_checkpointer or ops_store, with today's other importers on
store-allowlist.txt, whose count may only fall. Rule 2 (workflow code) applies once ops_interpreter exists.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

from fastapi.routing import APIRoute, iter_route_contexts

from ops_agents.api.app import create_app
from ops_agents.api.auth import principal, service_principal
from ops_service_kit.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
# Source trees of the Python workspace: reusable libraries and the services built from them.
SRC_ROOTS = sorted([*ROOT.glob("packages/*/src"), *ROOT.glob("services/*-service/src")])
ORDER = [
    "ops_contracts",
    "ops_policy",
    "ops_service_kit",
    "ops_identity",
    "ops_metering",
    "ops_store",
    "ops_storage",
    "ops_ingest",
    "ops_files",
    "ops_agent_kernel",
    "ops_agents.activities",
    "ops_checkpointer",
    "ops_agents.graphs",
    "ops_agents.store",
    "ops_tools",
    "ops_models",
    "ops_platform",
    "ops_interpreter",
    "ops_agents.api",
]
KIT = ROOT / "packages" / "ops_service_kit" / "src" / "ops_service_kit"
SETTINGS = KIT / "settings.py"
LOGGING = KIT / "logging.py"
PUBLIC_ROUTES = {"/health", "/healthz", "/readyz", "/v1/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


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
        # A user route depends on principal; an internal route (a scheduler's timer fire) on service_principal.
        if principal not in deps(route.dependant) and service_principal not in deps(route.dependant):
            out.append(f"route {sorted(route.methods or set())} {ctx.path or route.path} rule 5: no auth dependency")
    return checked


DRIVERS = ("sqlalchemy", "asyncpg")
STORE_PACKAGES = ("ops_checkpointer", "ops_store")
ALLOWLIST = ROOT / "store-allowlist.txt"
ALLOWLIST_HEADER = re.compile(r"^# (\d+) files")


def is_store(path: Path) -> bool:
    """A service's door to its database: a `store` package or a `store.py` module, or a package whose job is the
    database (the checkpointer, the store seam itself)."""
    return "store" in path.parts or path.name == "store.py" or any(f"/{p}/" in path.as_posix() for p in STORE_PACKAGES)


def imports_driver(tree: ast.AST) -> int | None:
    for node in ast.walk(tree):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        if any(n.split(".")[0] in DRIVERS for n in names):
            return getattr(node, "lineno", 0)
    return None


def allowlisted(text: str) -> tuple[int | None, set[str]]:
    lines = text.splitlines()
    header = ALLOWLIST_HEADER.match(lines[0]) if lines else None
    return (int(header.group(1)) if header else None), {
        line.strip() for line in lines[1:] if line.strip() and not line.startswith("#")
    }


def check_store_door(found: dict[str, int], out: list[str]) -> None:
    """Rule 15. `found` maps each source file outside a store that imports a driver to the import's line."""
    count, listed = allowlisted(ALLOWLIST.read_text()) if ALLOWLIST.exists() else (None, set[str]())
    for path, line in sorted(found.items()):
        if path not in listed:
            out.append(f"{path}:{line} rule 15: database driver imported outside a store; call a repository instead")
    out.extend(
        f"{p} rule 15: on store-allowlist.txt but no longer imports a driver; remove it"
        for p in sorted(listed - set(found))
    )
    if count != len(listed):
        out.append(f"store-allowlist.txt rule 15: the header says {count} and the file lists {len(listed)}")
    try:
        committed = subprocess.run(
            ["git", "show", "HEAD:store-allowlist.txt"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return  # an export or a first commit has nothing to compare with
    head = allowlisted(committed)[0]
    if head is not None and count is not None and count > head:
        out.append(
            f"store-allowlist.txt rule 15: {count} files, more than the {head} committed; move the queries instead"
        )


def main() -> int:
    out: list[str] = []
    drivers: dict[str, int] = {}
    for path in sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        check_layers(path, tree, out)
        check_env(path, tree, out)
        check_logging(path, tree, out)
        if not is_store(path) and (line := imports_driver(tree)) is not None:
            drivers[str(path.relative_to(ROOT))] = line
    check_store_door(drivers, out)
    check_fixtures(out)
    if check_routes(out) == 0:
        out.append("rule 5: no authenticated routes were found to check")
    for line in out:
        sys.stderr.write(line + "\n")
    sys.stdout.write(f"check_standards: {len(sources())} files, {len(out)} problems\n")
    return 1 if out else 0


if __name__ == "__main__":
    raise SystemExit(main())
