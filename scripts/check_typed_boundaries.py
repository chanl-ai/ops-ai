"""Refuses a boundary crossed without a model (docs/architecture/standards/api-and-models.md, MD1 and MD4; layers.md;
observability.md, OB1), in every package's and service's `src`:

  dict-any     a `dict[str, Any]` annotation; the summary counts them per layer (api, app, store, other)
  store-dict   a function under `store/` whose return type carries `dict[str, Any]`: a row leaves a store as a model,
               through `ops_store.rows`
  gather       `asyncio.gather(`: a request that fans out uses `asyncio.TaskGroup`
  task         `asyncio.create_task(` or `asyncio.ensure_future(`: a task that outlives its request goes through
               `ops_store.background.start`, one inside it is a TaskGroup child
  extra-allow  `extra="allow"` on a model: a body forwarded whole is an `ops_service_kit.http.Passthrough`
  body, reply  a route whose JSON body is not an `In`, or whose reply is not an `Out` all the way down, found by
               `ops_service_kit.contract.boundaries` on each service's app as its scripts/check_openapi.py builds it
  logging      `logging.getLogger(` outside ops_service_kit: a module logs through `ops_service_kit.logging.get_logger`
  print        `print(` outside ops_service_kit

What exists today is listed per member in `<member>/typed-boundaries-baseline.txt` (a route row names its operation
id), so only a new site is a finding; the member's lane takes its file to zero. `logging` and `print` are at zero and
no file can allow one. A row may only fall: `--update` lowers rows and drops fixed ones, and never raises or adds one
once a member has a file. A baseline read only against the code could be raised to match it, so `--commits` reads the
files' history: a commit that raises a row, adds a row or adds a file (a deleted and regenerated file is one) carries a
`Standards-exception:` trailer a listed maintainer approved (scripts/baseline_history.py).

  uv run python scripts/check_typed_boundaries.py            # findings, exit 0
  uv run python scripts/check_typed_boundaries.py --strict   # exit 1 when there is a finding
  uv run python scripts/check_typed_boundaries.py --commits  # exit 1 when a commit raised a baseline without a trailer
  uv run python scripts/check_typed_boundaries.py --update   # lower each baseline to today's findings
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import fastapi

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseline_history

from ops_service_kit.contract import boundaries

ROOT = Path(__file__).resolve().parents[1]
BASELINE_NAME = "typed-boundaries-baseline.txt"
# The commit that created the first member baseline; a commit after it that raises a row or adds a file needs a trailer.
BASELINES_BEGAN = "f2f7893e913d7d10257cf517d3273bc4696e6b18"
# The package that owns logging and the Passthrough base, where the zero-ceiling kinds do not apply.
KIT = "packages/ops_service_kit/"
ZERO = ("logging", "print")
ROUTE_KINDS = ("body", "reply")
FIX = {
    "dict-any": "name the shape: a model, a TypedDict, or a dataclass inside one layer",
    "store-dict": "return a model through ops_store.rows.rows() or one()",
    "gather": "fan out with asyncio.TaskGroup",
    "task": "use ops_store.background.start(), or a TaskGroup child for work inside the request",
    "extra-allow": "forbid extras; a body forwarded whole is ops_service_kit.http.Passthrough",
    "body": "take a body model that subclasses ops_service_kit.http.In",
    "reply": "declare response_model=Envelope[T] with T an ops_service_kit.http.Out",
    "logging": "log = ops_service_kit.logging.get_logger(__name__)",
    "print": "log the event with ops_service_kit.logging.get_logger",
}

# (kind, where): `where` is a file relative to the repository root, or `<member>#<operation id>` for a route.
Key = tuple[str, str]


def members(root: Path) -> list[Path]:
    """Every folder with a `src` the check reads: each package and each service."""
    return sorted(p.parent for p in [*root.glob("packages/*/src"), *root.glob("services/*-service/src")])


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _dict_any(node: ast.AST, names: dict[str, str] | None = None) -> bool:
    """`dict[str, Any]` or `dict[str, object]`, or the same under `Mapping`/`MutableMapping`, by any import spelling."""
    if not isinstance(node, ast.Subscript):
        return False
    base = _resolved(node.value, names or {})
    if base not in _DICTS:
        return False
    s = node.slice
    if not (isinstance(s, ast.Tuple) and len(s.elts) == 2):
        return False
    return _resolved(s.elts[0], names or {}) == "str" and _resolved(s.elts[1], names or {}) in _LOOSE


_DICTS = (
    "dict",
    "Dict",
    "typing.Dict",
    "typing.Mapping",
    "typing.MutableMapping",
    "collections.abc.Mapping",
    "collections.abc.MutableMapping",
)
_LOOSE = ("Any", "typing.Any", "object")


def _aliases(tree: ast.AST) -> dict[str, str]:
    """What each imported name stands for: `from asyncio import gather as g` makes `g` the dotted `asyncio.gather`, and
    `import asyncio as aio` makes `aio` stand for `asyncio`. Names are resolved by file, not by scope."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                names[a.asname or a.name] = f"{node.module}.{a.name}"
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    names[a.asname] = a.name
    return names


def _resolved(node: ast.expr, names: dict[str, str]) -> str:
    dotted = _dotted(node)
    head, _, rest = dotted.partition(".")
    return names.get(head, head) + (f".{rest}" if rest else "")


def _on_a_loop(node: ast.expr) -> bool:
    """A receiver that is an event loop: a name holding `loop`, or a call to get one."""
    if isinstance(node, ast.Call):
        return _dotted(node.func).rsplit(".", 1)[-1] in ("get_running_loop", "get_event_loop", "new_event_loop")
    return "loop" in _dotted(node).lower()


def findings(source: str, path: str) -> list[tuple[str, int]]:
    """Each (kind, line) in one file's source; `path` places it in a layer."""
    found: list[tuple[str, int]] = []
    in_store = "/store/" in path
    tree = ast.parse(source)
    names = _aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and any(
            isinstance(k, ast.Constant) and k.value == "extra" and isinstance(v, ast.Constant) and v.value == "allow"
            for k, v in zip(node.keys, node.values, strict=True)
        ):
            found.append(("extra-allow", node.lineno))
        if _dict_any(node, names):
            found.append(("dict-any", getattr(node, "lineno", 0)))
        elif (
            in_store
            and isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.returns is not None
            and any(_dict_any(n, names) for n in ast.walk(node.returns))
        ):
            found.append(("store-dict", node.lineno))
        if not isinstance(node, ast.Call):
            continue
        name = _resolved(node.func, names)
        if name == "asyncio.gather":
            found.append(("gather", node.lineno))
        elif name in ("asyncio.create_task", "asyncio.ensure_future") or (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in ("create_task", "ensure_future")
            and _on_a_loop(node.func.value)
        ):
            found.append(("task", node.lineno))
        elif name == "logging.getLogger":
            found.append(("logging", node.lineno))
        elif name == "print":
            found.append(("print", node.lineno))
        for kw in node.keywords:
            if kw.arg == "extra" and isinstance(kw.value, ast.Constant) and kw.value.value == "allow":
                found.append(("extra-allow", node.lineno))
    return found


def scan(root: Path) -> tuple[Counter[Key], dict[Key, list[int]]]:
    """Today's count per (kind, file) from the sources, and the lines behind each."""
    now: Counter[Key] = Counter()
    where: dict[Key, list[int]] = {}
    for member in members(root):
        for file in sorted((member / "src").rglob("*.py")):
            path = file.relative_to(root).as_posix()
            for kind, line in findings(file.read_text(), path):
                if path.startswith(KIT) and kind in (*ZERO, "extra-allow"):
                    continue
                now[(kind, path)] += 1
                where.setdefault((kind, path), []).append(line)
    return now, where


def walk(service: Path) -> list[tuple[str, str]]:
    """The route findings of one service: its scripts/check_openapi.py builds the app (or apps) its document comes
    from, and each app built is walked. Runs in the child process `--walk` starts."""
    apps: list[fastapi.FastAPI] = []
    build = fastapi.FastAPI.openapi

    def seen(self: fastapi.FastAPI) -> dict[str, Any]:
        if self not in apps:
            apps.append(self)
        return build(self)

    fastapi.FastAPI.openapi = seen  # type: ignore[method-assign]
    spec = importlib.util.spec_from_file_location("check_openapi", service / "scripts" / "check_openapi.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.document()
    return sorted({f for app in apps for f in boundaries(app)})


def routes(root: Path) -> Counter[Key]:
    """Every service's route findings, each service's app built in its own process, all at once."""
    services = [m for m in members(root) if (m / "scripts" / "check_openapi.py").exists()]
    children = {
        m: subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--walk", str(m)],
            cwd=m,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "PYTHONWARNINGS": "ignore"},
        )
        for m in services
    }
    now: Counter[Key] = Counter()
    for m, child in children.items():
        out, err = child.communicate()
        if child.returncode:
            raise SystemExit(f"check_typed_boundaries: building {m.name}'s app failed:\n{err[-2000:]}")
        name = m.relative_to(root).as_posix()
        for kind, op in json.loads(out.strip().splitlines()[-1]):
            now[(kind, f"{name}#{op}")] += 1
    return now


ROUTE_DECORATOR = re.compile(r"@\w+\.(?:get|post|put|patch|delete|api_route)\(|\bAPIRouter\(|\.add_api_route\(")


def unwalked(root: Path) -> list[str]:
    """Services with routes in `src` and no scripts/check_openapi.py: their routes are never walked, so a body or reply
    without a model could not be seen, and the baselines would say nothing about them."""
    out: list[str] = []
    for m in members(root):
        if not m.name.endswith("-service") or (m / "scripts" / "check_openapi.py").exists():
            continue
        if any(ROUTE_DECORATOR.search(f.read_text()) for f in (m / "src").rglob("*.py")):
            out.append(
                f"{m.relative_to(root).as_posix()}: has routes and no scripts/check_openapi.py, so none is walked"
            )
    return out


def read_baseline(text: str, member: str) -> Counter[Key]:
    base: Counter[Key] = Counter()
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            count, kind, where = line.split()
            base[(kind, f"{member}#{where}" if kind in ROUTE_KINDS else where)] = int(count)
    return base


def baselines(root: Path) -> Counter[Key]:
    base: Counter[Key] = Counter()
    for member in members(root):
        file = member / BASELINE_NAME
        if file.exists():
            base.update(read_baseline(file.read_text(), member.relative_to(root).as_posix()))
    return base


def problems(now: Counter[Key], base: Counter[Key], where: dict[Key, list[int]]) -> list[str]:
    found: list[str] = []
    for key in sorted(now):
        kind, at = key
        limit = 0 if kind in ZERO else base[key]
        if now[key] > limit:
            lines = f" at line {', '.join(str(n) for n in sorted(where[key]))}" if key in where else ""
            found.append(f"{at}: {now[key]} {kind} (allowed {limit}){lines}: {FIX[kind]}")
    return found


def layer(path: str) -> str:
    for name in ("api", "store"):
        if f"/{name}/" in path:
            return name
    return "app" if "/app/" in path or path.endswith("/app.py") else "other"


def render(member: str, rows: Counter[Key]) -> str:
    total = sum(rows.values())
    head = (
        f"# {total} boundaries crossed without a model in {member} (scripts/check_typed_boundaries.py). "
        "A row may only fall.\n"
    )

    def shown(k: Key) -> str:
        return k[1].split("#", 1)[1] if k[0] in ROUTE_KINDS else k[1]

    return head + "".join(f"{rows[k]} {k[0]} {shown(k)}\n" for k in sorted(rows, key=lambda k: (shown(k), k[0])))


def mine(name: str, key: Key) -> bool:
    return key[0] not in ZERO and (key[1].startswith(name + "/") or key[1].startswith(name + "#"))


def update(root: Path, now: Counter[Key]) -> int:
    """Lowers each member's baseline to today's counts. A member with no file gets today's; one with a file never
    gains or raises a row."""
    total = 0
    for member in members(root):
        name = member.relative_to(root).as_posix()
        file = member / BASELINE_NAME
        rows = Counter({k: n for k, n in now.items() if mine(name, k)})
        if file.exists():
            base = read_baseline(file.read_text(), name)
            rows = Counter({k: min(n, base[k]) for k, n in rows.items() if base[k]})
        if rows or file.exists():
            file.write_text(render(name, rows))
        total += sum(rows.values())
    return total


def summary(now: Counter[Key]) -> str:
    kinds: Counter[str] = Counter()
    layers: Counter[str] = Counter()
    for (kind, at), n in now.items():
        kinds[kind] += n
        if kind == "dict-any":
            layers[layer(at)] += n
    per_layer = ", ".join(f"{k} {layers[k]}" for k in ("api", "app", "store", "other"))
    return ", ".join(f"{k} {kinds[k]}" for k in FIX) + f" (dict-any by layer: {per_layer})"


def commit_problems(root: Path = ROOT) -> list[str]:
    """Baseline rows a commit raised, or files it added, without a Standards-exception: trailer."""
    return baseline_history.problems(
        root, BASELINES_BEGAN, [f"packages/*/{BASELINE_NAME}", f"services/*/{BASELINE_NAME}"]
    )


def main(root: Path = ROOT, *, with_routes: bool = True) -> int:
    if "--walk" in sys.argv:
        sys.stdout.write("\n" + json.dumps(walk(Path(sys.argv[sys.argv.index("--walk") + 1]))) + "\n")
        return 0
    if "--commits" in sys.argv:
        missing = commit_problems(root)
        sys.stdout.write(
            "\n".join(missing) + "\n" if missing else baseline_history.outcome("check_typed_boundaries") + "\n"
        )
        return 1 if missing else 0
    now, where = scan(root)
    if with_routes:
        now.update(routes(root))
    if "--update" in sys.argv:
        sys.stdout.write(f"check_typed_boundaries: baselines hold {update(root, now)} findings\n")
        return 0
    base = baselines(root)
    found = problems(now, base, where) + (unwalked(root) if with_routes else [])
    for line in found:
        sys.stderr.write(line + "\n")
    fell = sum(base.values()) - sum(min(n, base[k]) for k, n in now.items() if k[0] not in ZERO)
    note = f"; {fell} fixed since the baseline, run --update to lower it" if fell else ""
    sys.stdout.write(f"check_typed_boundaries: today {summary(now)}\n")
    sys.stdout.write(f"check_typed_boundaries: {len(found)} findings{note}\n")
    return 1 if found and "--strict" in sys.argv else 0


if __name__ == "__main__":
    raise SystemExit(main())
