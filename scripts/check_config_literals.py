"""Refuses configuration written into code instead of read from settings (docs/architecture/standards/
configuration.md, CF2 and CF3), in every package's and service's `src`:

  loopback  a URL that falls back to this machine when its setting is unset (`settings.x_url or
            "http://127.0.0.1:..."`). None is allowed: a missing address must stop the process at start
            (`Settings.require`), not send its first call to the wrong place. LOOPBACK_WAITING names the one still
            there; a baseline file cannot allow another, and the entry fails once its fallback is gone.
  timeout   a `timeout=` given as a number at a call. The value belongs on the setting (`Endpoint.timeout_s`).
  client    an `httpx.AsyncClient(` built outside `ops_identity.client`, which owns the one a service call uses
            (`ServiceClient.for_settings`).

Timeouts and clients that exist today are listed per member in `<member>/config-literals-baseline.txt`, so only a
new one is a finding; the member's lane takes its file to zero. A row may only fall: `--update` lowers rows and drops
fixed ones, and never raises or adds one once a member has a file.

  uv run python scripts/check_config_literals.py            # findings, exit 0
  uv run python scripts/check_config_literals.py --strict   # exit 1 when there is a finding
  uv run python scripts/check_config_literals.py --update   # lower each baseline to today's findings
"""

from __future__ import annotations

import ast
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_NAME = "config-literals-baseline.txt"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
# The module that owns the HTTP client a service call uses.
CLIENT_OWNER = "packages/ops_identity/src/ops_identity/client.py"
# The loopback fallbacks still in code. The list only shrinks: an entry whose fallback is gone fails the check until it
# is deleted here, and scripts/tests/test_check_config_literals.py fails when a file joins it.
LOOPBACK_WAITING = {
    # The request-transaction change owns this file and is rewriting it now; the line reads
    # Settings.endpoint("platform_internal") when that lands. Every process already requires the endpoint at start.
    "packages/ops_identity/src/ops_identity/fastapi.py": 1,
}

Key = tuple[str, str]  # (kind, path relative to the repository root)


def members(root: Path) -> list[Path]:
    """Every folder with a `src` the check reads: each package and each service."""
    return sorted(p.parent for p in [*root.glob("packages/*/src"), *root.glob("services/*-service/src")])


def _text(node: ast.expr) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return ""


def _is_async_client(func: ast.expr) -> bool:
    if isinstance(func, ast.Attribute):
        return func.attr == "AsyncClient" and isinstance(func.value, ast.Name) and func.value.id == "httpx"
    return isinstance(func, ast.Name) and func.id == "AsyncClient"


def findings(source: str) -> list[tuple[str, int]]:
    """Each (kind, line) in one file's source."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            # The first operand is the setting; a later one naming this machine is the fallback.
            if any(f"://{host}" in _text(v) for v in node.values[1:] for host in LOOPBACK_HOSTS):
                found.append(("loopback", node.lineno))
        elif isinstance(node, ast.Call):
            if _is_async_client(node.func):
                found.append(("client", node.lineno))
            for kw in node.keywords:
                number = isinstance(kw.value, ast.Constant) and type(kw.value.value) in (int, float)
                if kw.arg == "timeout" and number:
                    found.append(("timeout", kw.value.lineno))
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


def main(root: Path = ROOT) -> int:
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
