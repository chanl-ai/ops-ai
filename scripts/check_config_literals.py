"""Refuses configuration written into code instead of read from settings (docs/architecture/standards/
configuration.md, CF2 and CF3), in every package's and service's `src`:

  loopback  a URL that falls back to this machine when its setting is unset (`settings.x_url or
            "http://127.0.0.1:..."`). None is allowed: a missing address must stop the process at start
            (`Settings.require`), not send its first call to the wrong place. LOOPBACK_WAITING names any still
            there (none now); a baseline file cannot allow one, and an entry fails once its fallback is gone.
  timeout   a `timeout=` given as a number, an upper-case constant or arithmetic on them at a call, and an
            `httpx.Timeout(` holding one. The value belongs on the setting (`Endpoint.timeout_s`).
  client    an `httpx.AsyncClient(` or `httpx.Client(` built outside `ops_identity.client`, which owns the one a
            service call uses (`ServiceClient.for_settings`).

Timeouts and clients that exist today are listed per member in `<member>/config-literals-baseline.txt`, so only a
new one is a finding; the member's lane takes its file to zero. A row may only fall: `--update` lowers rows and drops
fixed ones, and never raises or adds one once a member has a file. A baseline file read only against the code could be
raised to match it, so `--commits` reads the files' history: a commit that raises a row or adds a file carries a
`Standards-exception:` trailer a maintainer approved.

  uv run python scripts/check_config_literals.py            # findings, exit 0
  uv run python scripts/check_config_literals.py --strict   # exit 1 when there is a finding
  uv run python scripts/check_config_literals.py --commits  # exit 1 when a commit raised a baseline without a trailer
  uv run python scripts/check_config_literals.py --update   # lower each baseline to today's findings
"""

from __future__ import annotations

import ast
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseline_history

ROOT = Path(__file__).resolve().parents[1]
BASELINE_NAME = "config-literals-baseline.txt"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
# The module that owns the HTTP client a service call uses.
CLIENT_OWNER = "packages/ops_identity/src/ops_identity/client.py"
# The loopback fallbacks still in code. The list only shrinks: an entry whose fallback is gone fails the check until it
# is deleted here, and scripts/tests/test_check_config_literals.py fails when a file joins it.
LOOPBACK_WAITING: dict[str, int] = {}
# The commit that created the first member baseline; a commit after it that raises a row or adds a file needs a trailer.
BASELINES_BEGAN = "d737b71434be868ceadc2b84fb28bcbb206a7ea1"

Key = tuple[str, str]  # (kind, path relative to the repository root)


def members(root: Path) -> list[Path]:
    """Every folder with a `src` the check reads: each package and each service."""
    return sorted(p.parent for p in [*root.glob("packages/*/src"), *root.glob("services/*-service/src")])


Names = dict[str, str]


def _text(node: ast.expr, strings: Names | None = None) -> str:
    """The text a string expression holds; a name stands for the string constant the file assigns it."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if isinstance(node, ast.Name) and strings:
        return strings.get(node.id, "")
    return ""


class Scope:
    """What one file's names stand for, found without running it: imports (`import httpx as h`), string constants and
    numbers assigned to a plain name at module level (a function's own are added as it is read: `numbers_in`)."""

    def __init__(self, tree: ast.AST) -> None:
        self.imports: Names = {}
        self.strings: Names = {}
        self.numbers: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for a in node.names:
                    self.imports[a.asname or a.name] = f"{node.module}.{a.name}"
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        self.imports[a.asname] = a.name
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for t in node.targets:
                    if isinstance(t, ast.Name) and isinstance(node.value.value, str):
                        self.strings[t.id] = node.value.value
        if isinstance(tree, ast.Module):
            self.numbers = numbers_in(tree.body)

    def dotted(self, node: ast.expr) -> str:
        parts: list[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return ""
        return ".".join([self.imports.get(node.id, node.id), *reversed(parts)])


def numbers_in(body: list[ast.stmt]) -> set[str]:
    """Names a block assigns a number (`t = 12`), not looking into nested functions or classes."""
    out: set[str] = set()
    todo: list[ast.AST] = list(body)
    while todo:
        node = todo.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and type(node.value.value) in (int, float)
        ):
            out.update(t.id for t in node.targets if isinstance(t, ast.Name))
        todo.extend(ast.iter_child_nodes(node))
    return out


def _is_client(func: ast.expr, scope: Scope) -> bool:
    """`httpx.AsyncClient`, `httpx.Client` or either imported by name or under another name."""
    return scope.dotted(func) in ("httpx.AsyncClient", "httpx.Client")


def _is_timeout_class(func: ast.expr, scope: Scope) -> bool:
    return scope.dotted(func) == "httpx.Timeout"


def _fixed(node: ast.expr, scope: Scope) -> bool:
    """A number, a name or attribute that is an upper-case constant (`RETRY_TIMEOUT`, `defaults.HTTP_TIMEOUT`) or that
    the file assigns a number, or arithmetic on them: a value written in code that a setting should hold."""
    if isinstance(node, ast.Constant):
        return type(node.value) in (int, float)
    if isinstance(node, ast.Name):
        return node.id.isupper() or node.id in scope.numbers
    if isinstance(node, ast.Attribute):
        return node.attr.isupper()
    if isinstance(node, ast.BinOp):
        return _fixed(node.left, scope) and _fixed(node.right, scope)
    return False


def _loopback(node: ast.expr, scope: Scope) -> bool:
    text = _text(node, scope.strings)
    return any(f"://{host}" in text for host in LOOPBACK_HOSTS)


def _nodes(node: ast.AST, numbers: set[str]) -> Iterator[tuple[ast.AST, set[str]]]:
    """Every node with the numbers its scope assigns: the module's, then a function's own, minus its parameters."""
    yield node, numbers
    inner = numbers
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        args = node.args
        params = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg] if a}
        inner = (numbers - params) | numbers_in(node.body)
    for child in ast.iter_child_nodes(node):
        yield from _nodes(child, inner)


def findings(source: str) -> list[tuple[str, int]]:
    """Each (kind, line) in one file's source."""
    found: list[tuple[str, int]] = []
    tree = ast.parse(source)
    scope = Scope(tree)
    for node, numbers in _nodes(tree, scope.numbers):
        scope.numbers = numbers
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            # The first operand is the setting; a later one naming this machine is the fallback.
            if any(_loopback(v, scope) for v in node.values[1:]):
                found.append(("loopback", node.lineno))
        elif isinstance(node, ast.IfExp):
            # `x if x else "http://localhost"`: either branch falling back to this machine.
            if _loopback(node.body, scope) or _loopback(node.orelse, scope):
                found.append(("loopback", node.lineno))
        elif isinstance(node, ast.Call):
            if _is_client(node.func, scope):
                found.append(("client", node.lineno))
            for kw in node.keywords:
                if kw.arg == "timeout" and _fixed(kw.value, scope):
                    found.append(("timeout", kw.value.lineno))
            # `httpx.Timeout(10.0, connect=3)` states the same limits as a number at the call.
            if _is_timeout_class(node.func, scope) and any(
                _fixed(a, scope) for a in [*node.args, *(k.value for k in node.keywords)]
            ):
                found.append(("timeout", node.lineno))
    return found


def current(root: Path) -> tuple[Counter[Key], dict[Key, list[int]]]:
    """Today's count per (kind, file), and the lines behind each."""
    now: Counter[Key] = Counter()
    where: dict[Key, list[int]] = {}
    for member in members(root):
        for file in sorted((member / "src").rglob("*.py")):
            path = file.relative_to(root).as_posix()
            for kind, line in findings(file.read_text()):
                if kind == "client" and path == CLIENT_OWNER:
                    continue
                now[(kind, path)] += 1
                where.setdefault((kind, path), []).append(line)
    return now, where


def read_baseline(text: str) -> Counter[Key]:
    base: Counter[Key] = Counter()
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            count, kind, path = line.split()
            base[(kind, path)] = int(count)
    return base


def baselines(root: Path) -> Counter[Key]:
    base: Counter[Key] = Counter()
    for member in members(root):
        file = member / BASELINE_NAME
        if file.exists():
            base.update(read_baseline(file.read_text()))
    return base


def allowed(key: Key, base: Counter[Key]) -> int:
    kind, path = key
    return LOOPBACK_WAITING.get(path, 0) if kind == "loopback" else base[key]


def problems(root: Path, now: Counter[Key], base: Counter[Key], where: dict[Key, list[int]]) -> list[str]:
    found: list[str] = []
    for key in sorted(now):
        kind, path = key
        limit = allowed(key, base)
        if now[key] > limit:
            lines = ", ".join(str(n) for n in sorted(where[key]))
            fix = {
                "loopback": "read the address from Settings and name it in Settings.require()",
                "timeout": "take the timeout from the setting (Endpoint.timeout_s)",
                "client": "use ServiceClient.for_settings, which owns the client",
            }[kind]
            found.append(f"{path}: {now[key]} {kind} (allowed {limit}) at line {lines}: {fix}")
    for path, limit in sorted(LOOPBACK_WAITING.items()):
        if (root / path).exists() and now[("loopback", path)] < limit:
            found.append(f"{path}: its loopback fallback is gone; lower or delete its LOOPBACK_WAITING entry")
    return found


def render(member: str, rows: Counter[Key]) -> str:
    total = sum(rows.values())
    head = (
        f"# {total} literal timeouts and HTTP clients built in {member} (scripts/check_config_literals.py). "
        "A row may only fall.\n"
    )
    return head + "".join(f"{rows[k]} {k[0]} {k[1]}\n" for k in sorted(rows, key=lambda k: (k[1], k[0])))


def update(root: Path, now: Counter[Key]) -> int:
    """Lowers each member's baseline to today's counts. A member with no file gets today's; one with a file never
    gains or raises a row."""
    total = 0
    for member in members(root):
        name = member.relative_to(root).as_posix()
        file = member / BASELINE_NAME
        mine = Counter({k: n for k, n in now.items() if k[0] != "loopback" and k[1].startswith(name + "/")})
        if file.exists():
            base = read_baseline(file.read_text())
            mine = Counter({k: min(n, base[k]) for k, n in mine.items() if base[k]})
        if mine or file.exists():
            file.write_text(render(name, mine))
        total += sum(mine.values())
    return total


def commit_problems(root: Path = ROOT) -> list[str]:
    """Baseline rows a commit raised, or files it added, without a Standards-exception: trailer."""
    return baseline_history.problems(
        root, BASELINES_BEGAN, [f"packages/*/{BASELINE_NAME}", f"services/*/{BASELINE_NAME}"]
    )


def main(root: Path = ROOT) -> int:
    if "--commits" in sys.argv:
        missing = commit_problems(root)
        sys.stdout.write(
            "\n".join(missing) + "\n" if missing else "check_config_literals: every baseline rise is approved\n"
        )
        return 1 if missing else 0
    now, where = current(root)
    if "--update" in sys.argv:
        sys.stdout.write(f"check_config_literals: baselines hold {update(root, now)} findings\n")
        return 0
    base = baselines(root)
    found = problems(root, now, base, where)
    for line in found:
        sys.stderr.write(line + "\n")
    fell = sum(base.values()) - sum(min(n, base[k]) for k, n in now.items() if k[0] != "loopback")
    note = f"; {fell} fixed since the baseline, run --update to lower it" if fell else ""
    sys.stdout.write(f"check_config_literals: {len(found)} findings{note}\n")
    return 1 if found and "--strict" in sys.argv else 0


if __name__ == "__main__":
    raise SystemExit(main())
