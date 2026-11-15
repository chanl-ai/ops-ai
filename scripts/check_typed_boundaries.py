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
once a member has a file.

  uv run python scripts/check_typed_boundaries.py            # findings, exit 0
  uv run python scripts/check_typed_boundaries.py --strict   # exit 1 when there is a finding
  uv run python scripts/check_typed_boundaries.py --update   # lower each baseline to today's findings
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import fastapi

from ops_service_kit.contract import boundaries

ROOT = Path(__file__).resolve().parents[1]
BASELINE_NAME = "typed-boundaries-baseline.txt"
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


def _dict_any(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Subscript) and _dotted(node.value) in ("dict", "Dict", "typing.Dict")):
        return False
    s = node.slice
    return (
        isinstance(s, ast.Tuple)
        and len(s.elts) == 2
        and [_dotted(e) for e in s.elts]
        in (
            ["str", "Any"],
            ["str", "typing.Any"],
        )
    )


def findings(source: str, path: str) -> list[tuple[str, int]]:
    """Each (kind, line) in one file's source; `path` places it in a layer."""
    found: list[tuple[str, int]] = []
    in_store = "/store/" in path
    for node in ast.walk(ast.parse(source)):
        if _dict_any(node):
            found.append(("dict-any", getattr(node, "lineno", 0)))
        elif (
            in_store
            and isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.returns is not None
            and any(_dict_any(n) for n in ast.walk(node.returns))
        ):
            found.append(("store-dict", node.lineno))
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if name == "asyncio.gather":
            found.append(("gather", node.lineno))
        elif name in ("asyncio.create_task", "asyncio.ensure_future"):
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


def main(root: Path = ROOT, *, with_routes: bool = True) -> int:
    if "--walk" in sys.argv:
        sys.stdout.write("\n" + json.dumps(walk(Path(sys.argv[sys.argv.index("--walk") + 1]))) + "\n")
        return 0
    now, where = scan(root)
    if with_routes:
        now.update(routes(root))
    if "--update" in sys.argv:
        sys.stdout.write(f"check_typed_boundaries: baselines hold {update(root, now)} findings\n")
        return 0
    base = baselines(root)
    found = problems(now, base, where)
    for line in found:
        sys.stderr.write(line + "\n")
    fell = sum(base.values()) - sum(min(n, base[k]) for k, n in now.items() if k[0] not in ZERO)
    note = f"; {fell} fixed since the baseline, run --update to lower it" if fell else ""
    sys.stdout.write(f"check_typed_boundaries: today {summary(now)}\n")
    sys.stdout.write(f"check_typed_boundaries: {len(found)} findings{note}\n")
    return 1 if found and "--strict" in sys.argv else 0


if __name__ == "__main__":
    raise SystemExit(main())
