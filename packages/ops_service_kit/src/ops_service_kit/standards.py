"""The code rules every service holds, read from its source and its app: the environment is read in one module, every
route authenticates, nothing prints or builds its own logger (rules 4 to 6 of the engineering standards), and only the
one model client posts to models-service's model routes (SC1).

  problems = standards.check(create_app(settings), settings_module="ops_service_kit.settings", authenticated=[...])

`check` returns one `path:line rule N: ...` string for each breach, and one for a route check that saw no route, so a
check that silently finds nothing fails. A script or test calls it and prints the list; services/agents-service's
`scripts/check_standards.py` runs it beside its layer rules. It reads the workspace's sources, so it runs from a
checkout and is not part of a running service.
"""

from __future__ import annotations

import ast
import importlib.util
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

ROOT = Path(__file__).resolve().parents[4]
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
# What every module names its `get_logger(__name__)`.
LOGGER_NAMES = {"log", "logger"}
# Request-model fields that hold a name a person types: they take `ops_service_kit.names.Name`, not a bare `str`.
NAME_FIELDS = frozenset({"name", "title", "label", "display_name"})
# `path:Class.field` of each one still on a bare `str`; the list only shrinks.
NAME_BASELINE = ROOT / "packages/ops_service_kit/name-fields-baseline.txt"
# Routes a caller reaches without signing in: the probes, the API documents and the loaders a page fetches.
PUBLIC_ROUTES = frozenset(
    {
        "/health",
        "/health/background",
        "/healthz",
        "/readyz",
        "/v1/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
    }
)


def is_logging_module(path: Path) -> bool:
    """The kit's own log setup, the one file that may build loggers; by name, so a copy of the tree is read the same."""
    return path.name == "logging.py" and path.parent.name == "ops_service_kit"


def source_roots() -> list[Path]:
    """Source trees of the Python workspace: reusable libraries and the services built from them."""
    return sorted([*ROOT.glob("packages/*/src"), *ROOT.glob("services/*-service/src")])


def settings_path(settings_module: str) -> Path:
    """The file of the one module allowed to read the environment."""
    spec = importlib.util.find_spec(settings_module)
    if spec is None or spec.origin is None:
        raise ValueError(f"settings module {settings_module} is not importable")
    return Path(spec.origin).resolve()


def check(
    app: FastAPI,
    *,
    settings_module: str,
    authenticated: Iterable[Callable[..., Any]] = (),
    public: Iterable[str] = (),
    roots: Sequence[Path] | None = None,
) -> list[str]:
    """Rule 4 (the environment is read only in `settings_module`), rule 5 (each route of `app` outside `public` and
    the probes depends on one of `authenticated`) and rule 6 (no print, no `logging.getLogger`, one log setup, event
    names that can be searched) over every source file under `roots` (the workspace's by default)."""
    out: list[str] = []
    allowed = settings_path(settings_module)
    baseline: set[str] = set(NAME_BASELINE.read_text().split()) if NAME_BASELINE.exists() else set()
    for src in roots if roots is not None else source_roots():
        for path in sorted(src.rglob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            out += check_env(path, tree, allowed)
            out += check_logging(path, tree)
            out += check_names(path, tree, baseline)
            out += check_model_calls(path, tree)
    if check_routes(app, set(authenticated), PUBLIC_ROUTES | set(public), out) == 0:
        out.append("rule 5: no authenticated routes were found to check")
    return out


def _at(path: Path) -> Path:
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def check_env(path: Path, tree: ast.AST, allowed: Path) -> list[str]:
    if path.resolve() == allowed:
        return []
    out: list[str] = []
    os_names = {"os"} | {
        a.asname for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names if a.name == "os" and a.asname
    }
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in {"environ", "getenv"}
            and isinstance(node.value, ast.Name)
            and node.value.id in os_names
        ) or (
            isinstance(node, ast.ImportFrom)
            and node.module == "os"
            and any(a.name in {"environ", "getenv"} for a in node.names)
        ):
            out.append(f"{_at(path)}:{node.lineno} rule 4: environment read outside {_at(allowed)}")
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("dotenv"):
            out.append(f"{_at(path)}:{node.lineno} rule 4: dotenv import")
    return out


# models-service's model routes. Only the one client posts to them; models-service serves them.
MODEL_ROUTES = ("/v1/models/chat/completions", "/v1/models/embeddings")


def _owns_model_routes(path: Path) -> bool:
    """The one client (`ops_service_kit.model_calls`), this check's own list, and models-service itself; by name, as
    `is_logging_module`."""
    kit = path.parent.name == "ops_service_kit" and path.name in {"model_calls.py", "standards.py"}
    return kit or "ops_models" in path.parts


def check_model_calls(path: Path, tree: ast.AST) -> list[str]:
    """SC1 (docs/architecture/standards/security.md): a service calls a model through `ops_service_kit.model_calls`,
    so every call carries the service's key, its refusal codes and its usage the same way; a module that names a
    model route itself has its own copy of the call."""
    if _owns_model_routes(path):
        return []
    return [
        f"{_at(path)}:{node.lineno} rule SC1: a model call outside ops_service_kit.model_calls"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith(MODEL_ROUTES)
    ]


def model_call_breaches(roots: Sequence[Path]) -> list[str]:
    """`check_model_calls` over every source file under `roots`."""
    return [
        found
        for src in roots
        for path in sorted(src.rglob("*.py"))
        for found in check_model_calls(path, ast.parse(path.read_text(), filename=str(path)))
    ]


def check_names(path: Path, tree: ast.AST, baseline: set[str]) -> list[str]:
    """MD5 (docs/architecture/standards/api-and-models.md): a request model's name, title or label field is a `Name`:
    trimmed, never blank, no control character, capped at its column. A bare `str` is refused unless it carries a
    `pattern` or is in the baseline."""
    at = _at(path)
    out: list[str] = []
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        if not any(isinstance(b, ast.Name) and b.id == "In" for b in cls.bases):
            continue
        for node in cls.body:
            if not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)):
                continue
            if node.target.id not in NAME_FIELDS or ast.unparse(node.annotation) not in {"str", "str | None"}:
                continue
            if node.value is not None and "pattern" in ast.unparse(node.value):
                continue
            key = f"{at}:{cls.name}.{node.target.id}"
            if key not in baseline:
                out.append(f"{at}:{node.lineno} MD5 names: {cls.name}.{node.target.id} is a bare str; use names.Name")
    return out


def check_logging(path: Path, tree: ast.AST) -> list[str]:
    at = _at(path)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            out.append(f"{at}:{node.lineno} rule 6: print in package code")
        if (not is_logging_module(path) and (isinstance(node, ast.Attribute) and node.attr == "getLogger")) or (
            isinstance(node, ast.ImportFrom)
            and node.module == "logging"
            and any(a.name == "getLogger" for a in node.names)
        ):
            out.append(f"{at}:{node.lineno} rule 6: logging.getLogger outside ops_service_kit.logging")
        if not is_logging_module(path) and isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            out += check_log_call(at, path, node, node.func)
    return out


def check_log_call(at: Path, path: Path, node: ast.Call, func: ast.Attribute) -> list[str]:
    """Rule 6b: one log setup (a second format, or uvicorn's own handlers, would print lines a collector cannot
    parse), and event names a search can find (a value in the event makes every line a different event)."""
    out: list[str] = []
    if func.attr == "basicConfig":
        out.append(f"{at}:{node.lineno} rule 6b: logging.basicConfig; a process calls configure_logging")
    receiver = func.value.id if isinstance(func.value, ast.Name) else None
    if receiver == "uvicorn" and func.attr in {"run", "Config"} and path.is_relative_to(ROOT / "services"):
        kw = {k.arg: (k.value.value if isinstance(k.value, ast.Constant) else k.value) for k in node.keywords}
        if (
            "log_level" in kw
            or "log_config" not in kw
            or kw["log_config"] is not None
            or kw.get("access_log") is not False
        ):
            out.append(
                f"{at}:{node.lineno} rule 6b: uvicorn.{func.attr} needs log_config=None and access_log=False and no "
                "log_level, so its lines reach configure_logging's handler"
            )
    if receiver in LOGGER_NAMES and func.attr in LOG_METHODS:
        first = node.args[0] if node.args else None
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)) or len(node.args) > 1:
            out.append(f"{at}:{node.lineno} rule 6b: a log call's event is a string literal and its values keywords")
    return out


def _dependencies(dependant: object) -> set[object]:
    found: set[object] = set()
    stack = [dependant]
    while stack:
        d = stack.pop()
        for sub in getattr(d, "dependencies", []):
            found.add(sub.call)
            stack.append(sub)
    return found


def check_routes(app: FastAPI, authenticated: set[Callable[..., Any]], public: Iterable[str], out: list[str]) -> int:
    """Appends each route with no authentication dependency to `out`; returns how many routes it checked. Included
    routers are nested, and `iter_route_contexts` flattens them with their effective paths."""
    skipped = set(public)
    checked = 0
    for ctx in iter_route_contexts(app.routes):
        route = ctx.original_route
        path = ctx.path or getattr(route, "path", "")
        if not isinstance(route, APIRoute) or path in skipped:
            continue
        checked += 1
        if not _dependencies(route.dependant) & authenticated:
            out.append(f"route {sorted(route.methods or set())} {path} rule 5: no auth dependency")
    return checked
