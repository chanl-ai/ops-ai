"""How effective the tests of a change are, measured on the changed lines, never counted.

Four parts, each a section of the report:

1. Mutation on the changed lines. Every changed line of Python under a folder the profile's "Tests" table maps to a
   tests folder gets small faults (`==` to `!=`, `<` to `<=`, `and` to `or`, `True` to `False`, a number plus one,
   a string changed, `not` dropped, `return x` to `return None`). The suite runs once with coverage contexts, so each
   fault runs only the tests that reach its line; a fault no test reaches is "no coverage". The score is
   killed / (killed + survived), as Stryker defines it; timeouts are listed apart. Changed TypeScript under
   `apps/console/src/lib` is mutated the same way on its lines and run with `node --test` on the test beside it.
2. Tests worth deleting: a test with no assertion, an assertion that is always true, assertions only on a mock's
   calls, a body identical to another test's, or a subject that is only a library.
3. Timing: fixed sleeps and wall-clock waits.
4. Failure modes with no test: the rows of the design page's "Acceptance criteria and tests" (or "Acceptance tests")
   whose use case id, test name or words are found in no test file of the change.

  python3 scripts/agents/test_audit.py --base origin/main [--design docs/design/<area>/<topic>.md]
         [--paths services/kb-service/src/ops_kb/app.py …] [--max-mutants 60] [--no-mutate] [--json] [--out FILE]
  python3 scripts/agents/test_audit.py --self-test      the static rules and the mutator on a fixture package

The profile's "Tests" section owns where tests live, how they run and what they need; this script owns none of it.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import operator
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_profile import Profile, load, plain

ASSERT_CALLS = re.compile(r"\b(assert\w*|expect|check|raises|fail|pytest\.raises|assertRaises)\b")
MOCK_ONLY = re.compile(r"\.(assert_called|assert_any_call|assert_not_called|assert_awaited|call_count|called)\b")
SLEEP = re.compile(r"\b(time\.sleep|asyncio\.sleep|waitForTimeout|setTimeout|sleep)\(\s*\d")
TS_TEST_CASE = re.compile(r"^\s*(?:test|it)\(\s*(['\"`])(.+?)\1", re.M)
UC_ID = re.compile(r"\buc-\d{3}\b")


@dataclass
class Finding:
    file: str
    line: int
    name: str
    reason: str


@dataclass
class Mutant:
    file: str
    line: int
    change: str
    status: str = "pending"  # killed | survived | no coverage | timeout | error
    tests: list[str] = field(default_factory=list)
    detail: str = ""


# ----------------------------------------------------------------------------------------------- git and profile


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def changed_lines(root: Path, base: str, paths: list[str] | None) -> dict[str, set[int]]:
    """New-side line numbers added or modified since `base`, per file, from a zero-context diff."""
    merge_base = git(root, "merge-base", base, "HEAD").strip()
    diff = git(root, "diff", "--unified=0", merge_base, "HEAD", "--", *(paths or []))
    out: dict[str, set[int]] = {}
    path = ""
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            path = path[2:] if path.startswith("b/") else path
            if path != "/dev/null":
                out.setdefault(path, set())
        elif raw.startswith("@@") and path:
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", raw)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or 1)
                out[path].update(range(start, start + count))
    return {p: lines for p, lines in out.items() if (root / p).is_file()}


def glob_regex(pattern: str) -> re.Pattern[str]:
    """A profile glob with `<name>` and `<module>` and `<file>` as captures, `**` crossing folders."""
    regex = re.escape(pattern)
    for token in ("name", "module", "file"):
        regex = regex.replace(re.escape(f"<{token}>"), f"(?P<{token}>[^/]+)")
    regex = regex.replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.compile("^" + regex + "$")


@dataclass
class TestHome:
    """Where a code file's tests live and how to run them, from one "Tests" row of the profile."""

    tests: str
    runner: list[str]
    needs: str
    kind: str  # python | node


def test_home(profile: Profile, path: str) -> TestHome | None:
    for row in profile.table("Tests", "Runner (from the code's folder)"):
        code = plain(row["Code"])
        if code.startswith("a use case") or code.startswith("scripts/"):
            continue
        m = glob_regex(code).match(path)
        if not m:
            continue
        subs = m.groupdict()
        tests = plain(row["Tests"])
        runner = plain(row["Runner (from the code's folder)"])
        for key, value in subs.items():
            tests = tests.replace(f"<{key}>", value)
            runner = runner.replace(f"<{key}>", value)
        kind = "node" if "node" in runner else "python"
        return TestHome(tests=tests, runner=shlex.split(runner), needs=plain(row["Needs"]), kind=kind)
    return None


# ----------------------------------------------------------------------------------------------- static audit


def python_test_findings(path: Path, rel: str) -> tuple[list[Finding], list[Finding], list[tuple[str, str]]]:
    """Tests worth deleting and timing smells in one Python test file; bodies by hash for duplicate detection."""
    weak: list[Finding] = []
    timing: list[Finding] = []
    bodies: list[tuple[str, str]] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        return [Finding(rel, e.lineno or 0, "", f"does not parse: {e.msg}")], [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or not node.name.startswith("test"):
            continue
        src = ast.unparse(node)
        asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
        raises = [n for n in ast.walk(node) if isinstance(n, ast.Call) and "raises" in ast.unparse(n.func)]
        helper_checks = [
            n for n in ast.walk(node) if isinstance(n, ast.Call) and ASSERT_CALLS.search(ast.unparse(n.func))
        ]
        mock_asserts = [n for n in ast.walk(node) if isinstance(n, ast.Call) and MOCK_ONLY.search(ast.unparse(n.func))]
        if not asserts and not raises and not helper_checks:
            weak.append(Finding(rel, node.lineno, node.name, "no assertion: it cannot fail"))
        elif asserts and all(_always_true(a.test) for a in asserts) and not raises and not helper_checks:
            weak.append(Finding(rel, node.lineno, node.name, "every assertion is always true"))
        elif mock_asserts and len(mock_asserts) == len(asserts) + len(helper_checks) - len(raises):
            weak.append(Finding(rel, node.lineno, node.name, "asserts only on a mock's calls, not on behaviour"))
        for n in ast.walk(node):
            if isinstance(n, ast.Call) and SLEEP.search(ast.unparse(n)[:40]):
                timing.append(Finding(rel, n.lineno, node.name, f"fixed wait: {ast.unparse(n)[:60]}"))
        normalized = re.sub(r"\btest_\w+", "test_", src)
        bodies.append((hashlib.sha1(normalized.encode()).hexdigest(), f"{rel}:{node.lineno} {node.name}"))
        for d in node.decorator_list:
            text = ast.unparse(d)
            if ("skip" in text or "xfail" in text) and "reason" not in text:
                weak.append(Finding(rel, node.lineno, node.name, "skipped or expected to fail with no reason"))
    return weak, timing, bodies


def _always_true(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Constant):
        return bool(expr.value)
    if isinstance(expr, ast.Compare) and len(expr.ops) == 1:
        left, right = ast.unparse(expr.left), ast.unparse(expr.comparators[0])
        if left == right and isinstance(expr.ops[0], ast.Eq | ast.Is | ast.LtE | ast.GtE):
            return True
        if isinstance(expr.left, ast.Constant) and isinstance(expr.comparators[0], ast.Constant):
            ops = {
                ast.Eq: operator.eq,
                ast.NotEq: operator.ne,
                ast.Lt: operator.lt,
                ast.LtE: operator.le,
                ast.Gt: operator.gt,
                ast.GtE: operator.ge,
            }
            fn = ops.get(type(expr.ops[0]))
            try:
                return bool(fn(expr.left.value, expr.comparators[0].value)) if fn else False
            except TypeError:
                return False
    return False


def node_test_findings(path: Path, rel: str) -> tuple[list[Finding], list[Finding], list[tuple[str, str]]]:
    """The same rules for a TypeScript or JavaScript test file, by text."""
    weak: list[Finding] = []
    timing: list[Finding] = []
    bodies: list[tuple[str, str]] = []
    text = path.read_text(encoding="utf-8")
    starts = [(m.start(), m.group(2), text[: m.start()].count("\n") + 1) for m in TS_TEST_CASE.finditer(text)]
    for i, (start, name, line) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        body = text[start:end]
        if not ASSERT_CALLS.search(body):
            weak.append(Finding(rel, line, name, "no assertion: it cannot fail"))
        elif re.search(
            r"(expect|assert)\(\s*true\s*\)\.toBe\(\s*true\s*\)|assert\.ok\(\s*true\s*\)|assert\(true\)", body
        ):
            weak.append(Finding(rel, line, name, "an assertion that is always true"))
        for m in SLEEP.finditer(body):
            timing.append(Finding(rel, line + body[: m.start()].count("\n"), name, f"fixed wait: {m.group(0)}"))
        normalized = re.sub(r"(test|it)\(\s*(['\"`]).+?\2", "test(", body).strip()
        bodies.append((hashlib.sha1(normalized.encode()).hexdigest(), f"{rel}:{line} {name}"))
    return weak, timing, bodies


def static_audit(root: Path, test_files: list[str]) -> tuple[list[Finding], list[Finding], list[Finding]]:
    weak: list[Finding] = []
    timing: list[Finding] = []
    seen: dict[str, str] = {}
    duplicates: list[Finding] = []
    for rel in test_files:
        path = root / rel
        if not path.is_file():
            continue
        if rel.endswith(".py"):
            w, t, bodies = python_test_findings(path, rel)
        elif rel.endswith((".ts", ".mjs", ".js", ".tsx")):
            w, t, bodies = node_test_findings(path, rel)
        else:
            continue
        weak += w
        timing += t
        for digest, where in bodies:
            if digest in seen and seen[digest] != where:
                f, ln, name = where.split(":")[0], int(where.split(":")[1].split()[0]), where.split()[-1]
                duplicates.append(Finding(f, ln, name, f"same body as {seen[digest]}"))
            seen.setdefault(digest, where)
    return weak, timing, duplicates


# ----------------------------------------------------------------------------------------------- failure modes


def design_failure_modes(page: Path) -> list[str]:
    """The rows of the design's acceptance sections, one line each: the first cell and any use case id or test name."""
    text = page.read_text(encoding="utf-8")
    modes: list[str] = []
    capture = False
    for line in text.splitlines():
        if line.startswith("#"):
            capture = bool(re.search(r"acceptance|failure modes", line, re.I))
            continue
        if not capture:
            continue
        if (
            line.startswith("|")
            and not re.match(r"^\|\s*-{3,}", line)
            and not re.match(r"^\|\s*(id|#|failure mode|criterion|story)\s*\|", line, re.I)
        ):
            cells = [c.strip() for c in line.strip("|").split("|")]
            modes.append(" | ".join(c for c in cells if c)[:160])
        elif re.match(r"^\s*(\d+\.|-|\*)\s+", line):
            modes.append(line.strip().lstrip("-*0123456789. ")[:160])
    return modes


def uncovered_failure_modes(root: Path, modes: list[str], test_files: list[str]) -> list[dict[str, str]]:
    corpus = "\n".join(
        (root / f).read_text(encoding="utf-8", errors="ignore") for f in test_files if (root / f).is_file()
    ).lower()
    out = []
    for mode in modes:
        ids = UC_ID.findall(mode)
        names = re.findall(r"\btest_\w+|test-uc-\d{3}-\w+", mode)
        keys = [k.lower() for k in ids + names]
        if keys:
            covered = any(k in corpus for k in keys)
        else:
            words = [
                w
                for w in re.findall(r"[a-z]{5,}", mode.lower())
                if w not in {"given", "when", "then", "layer", "revert", "should"}
            ]
            covered = bool(words) and sum(w in corpus for w in words) >= max(2, len(words) // 2)
        if not covered:
            out.append({"failure_mode": mode, "looked_for": ", ".join(keys) or "its words"})
    return out


# ----------------------------------------------------------------------------------------------- mutation


def python_mutants(path: Path, rel: str, lines: set[int]) -> list[tuple[Mutant, str]]:
    """(mutant, mutated source) per fault on a changed line, from the file's AST, by text replacement."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    text_lines = source.splitlines(keepends=True)
    offsets = [0]
    for ln in text_lines:
        offsets.append(offsets[-1] + len(ln))

    def pos(node: ast.AST, end: bool = False) -> int:
        line = node.end_lineno if end else node.lineno  # type: ignore[attr-defined]
        col = node.end_col_offset if end else node.col_offset  # type: ignore[attr-defined]
        return offsets[line - 1] + col

    docstrings = {
        id(n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
    }
    swaps: dict[type, tuple[str, str]] = {
        ast.Eq: ("==", "!="),
        ast.NotEq: ("!=", "=="),
        ast.Lt: ("<", "<="),
        ast.LtE: ("<=", "<"),
        ast.Gt: (">", ">="),
        ast.GtE: (">=", ">"),
        ast.In: ("in", "not in"),
        ast.NotIn: ("not in", "in"),
        ast.Is: ("is", "is not"),
        ast.IsNot: ("is not", "is"),
    }
    out: list[tuple[Mutant, str]] = []

    def replace(start: int, end: int, new: str, line: int, change: str) -> None:
        out.append((Mutant(rel, line, change), source[:start] + new + source[end:]))

    for node in ast.walk(tree):
        if not hasattr(node, "lineno") or node.lineno not in lines:
            continue
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in swaps:
            old, new = swaps[type(node.ops[0])]
            start, end = pos(node.left, True), pos(node.comparators[0])
            gap = source[start:end]
            i = gap.find(old)
            if i >= 0 and (old != "in" or "not in" not in gap):
                replace(start + i, start + i + len(old), new, node.lineno, f"{old} → {new}")
        elif isinstance(node, ast.BoolOp) and len(node.values) >= 2:
            old, new = ("and", "or") if isinstance(node.op, ast.And) else ("or", "and")
            start, end = pos(node.values[0], True), pos(node.values[1])
            i = source[start:end].find(old)
            if i >= 0:
                replace(start + i, start + i + len(old), new, node.lineno, f"{old} → {new}")
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            start, end = pos(node), pos(node.operand)
            replace(start, end, "", node.lineno, "not dropped")
        elif isinstance(node, ast.Constant) and id(node) not in docstrings:
            start, end = pos(node), pos(node, True)
            if isinstance(node.value, bool):
                replace(start, end, str(not node.value), node.lineno, f"{node.value} → {not node.value}")
            elif isinstance(node.value, int) and not isinstance(node.value, bool):
                replace(start, end, str(node.value + 1), node.lineno, f"{node.value} → {node.value + 1}")
            elif isinstance(node.value, str) and node.value and len(node.value) < 80 and source[start] in "'\"":
                quote = source[start]
                replace(
                    start,
                    end,
                    f"{quote}{node.value}X{quote}",
                    node.lineno,
                    f"{node.value[:20]!r} → {node.value[:20] + 'X'!r}",
                )
        elif isinstance(node, ast.Return) and node.value is not None and not isinstance(node.value, ast.Constant):
            start, end = pos(node.value), pos(node.value, True)
            replace(start, end, "None", node.lineno, "return value → None")
        elif isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult):
            old, new = {ast.Add: ("+", "-"), ast.Sub: ("-", "+"), ast.Mult: ("*", "+")}[type(node.op)]
            start, end = pos(node.left, True), pos(node.right)
            i = source[start:end].find(old)
            if i >= 0:
                replace(start + i, start + i + len(old), new, node.lineno, f"{old} → {new}")
    return out


TS_SWAPS = [
    ("===", "!=="),
    ("!==", "==="),
    ("&&", "||"),
    ("||", "&&"),
    (">=", ">"),
    ("<=", "<"),
    (" true", " false"),
    (" false", " true"),
]


def node_mutants(path: Path, rel: str, lines: set[int]) -> list[tuple[Mutant, str]]:
    """Line-level faults in TypeScript or JavaScript: operator and literal swaps, one per occurrence."""
    source = path.read_text(encoding="utf-8")
    text_lines = source.splitlines(keepends=True)
    out: list[tuple[Mutant, str]] = []
    for ln in sorted(lines):
        if ln > len(text_lines):
            continue
        line = text_lines[ln - 1]
        code = line.split("//")[0]
        for old, new in TS_SWAPS:
            i = code.find(old)
            if i >= 0:
                mutated = line[:i] + new + line[i + len(old) :]
                out.append(
                    (
                        Mutant(rel, ln, f"{old.strip()} → {new.strip()}"),
                        "".join(text_lines[: ln - 1]) + mutated + "".join(text_lines[ln:]),
                    )
                )
        for m in re.finditer(r"(?<![\w.])(\d+)(?![\w.])", code):
            n = int(m.group(1))
            mutated = line[: m.start()] + str(n + 1) + line[m.end() :]
            out.append(
                (Mutant(rel, ln, f"{n} → {n + 1}"), "".join(text_lines[: ln - 1]) + mutated + "".join(text_lines[ln:]))
            )
            break
    return out


def covering_tests(data_file: Path, source_file: Path) -> dict[int, list[str]]:
    """Line → test ids from a coverage database written with dynamic test contexts."""
    try:
        from coverage import CoverageData  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError:
        return {}
    data = CoverageData(basename=str(data_file))
    data.read()
    name = next((f for f in data.measured_files() if Path(f).resolve() == source_file.resolve()), None)
    if not name:
        return {}
    out: dict[int, list[str]] = {}
    for line, contexts in (data.contexts_by_lineno(name) or {}).items():
        tests = sorted({c.split("|")[0] for c in contexts if c})
        if tests:
            out[line] = tests
    return out


def test_database(profile: Profile, root: Path) -> dict[str, str]:
    """A throwaway test database for this run, made the way the profile says, or the one make already set."""
    env = dict(os.environ)
    if env.get("OPS_TEST_DATABASE_URL"):
        env["OPS_DATABASE_URL"] = env["OPS_TEST_DATABASE_URL"]
        return env
    template = profile.value("Tests", "URL template", "Test database")
    name = profile.value("Tests", "Name for an audit run", "Test database").split()[0]
    name = name.replace("<pid>", str(os.getpid())).replace("<hex>", secrets.token_hex(3))
    url = template.replace("<name>", name)
    made = subprocess.run(
        ["uv", "run", "--quiet", "python", "scripts/test_db.py", url],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if made.returncode != 0:
        print(f"test database: {made.stderr.strip()[-300:]}", file=sys.stderr)
    env["OPS_TEST_DATABASE_URL"] = env["OPS_DATABASE_URL"] = url
    return env


# (cwd, tests folder, module) → the coverage database and the seconds its baseline took, for the life of one audit.
_BASELINES: dict[tuple[str, str, str], tuple[Path, float]] = {}


def drop_baselines() -> None:
    for cov_file, _ in _BASELINES.values():
        shutil.rmtree(cov_file.parent, ignore_errors=True)
    _BASELINES.clear()


def baseline_command(runner: list[str], module: str, tests_dir: str) -> list[str]:
    """The runner's command with coverage contexts; `uv run` gets pytest-cov as an extra, a plain python needs it."""
    cmd = list(runner)
    if cmd[:2] == ["uv", "run"] and "--with" not in cmd:
        cmd[2:2] = ["--quiet", "--with", "pytest-cov"]
    return [*cmd, f"--cov={module}", "--cov-context=test", "--cov-report=", tests_dir]


def run_python_mutants(
    root: Path, home: TestHome, rel: str, lines: set[int], *, env: dict[str, str], budget: int, timeout_factor: float
) -> tuple[list[Mutant], str]:
    """Baseline run with coverage contexts, then each mutant against the tests that reach its line."""
    src = root / rel
    candidates = python_mutants(src, rel, lines)[:budget]
    if not candidates:
        return [], "no mutable construct on the changed lines"
    tests_path = Path(home.tests.rstrip("/"))
    cwd = root / tests_path.parent
    tests_dir = tests_path.name
    module = rel.rsplit("/src/", maxsplit=1)[-1].split("/", maxsplit=1)[0] if "/src/" in rel else src.stem
    # A mutant the same size as the original, written within the same second, matches the cached bytecode's header,
    # and Python would import the unmutated .pyc: no bytecode is written or read for these runs.
    env = {**env, "PYTHONDONTWRITEBYTECODE": "1"}
    for cache in src.parent.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    # One baseline per tests folder, shared by every changed file it covers: the suite with coverage is the slow part.
    key = (str(cwd), tests_dir, module)
    if key not in _BASELINES:
        cov_file = Path(tempfile.mkdtemp(prefix="ops-audit-")) / ".coverage"
        started = time.monotonic()
        base = subprocess.run(
            baseline_command(home.runner, module, tests_dir),
            cwd=cwd,
            env={**env, "COVERAGE_FILE": str(cov_file)},
            capture_output=True,
            text=True,
            check=False,
        )
        baseline_s = time.monotonic() - started
        if base.returncode != 0:
            tail = (base.stdout + base.stderr).strip().splitlines()[-5:]
            shutil.rmtree(cov_file.parent, ignore_errors=True)
            return [], "baseline suite is red or coverage could not run: " + " | ".join(tail)
        _BASELINES[key] = (cov_file, baseline_s)
    cov_file, baseline_s = _BASELINES[key]
    by_line = covering_tests(cov_file, src)
    original = src.read_text(encoding="utf-8")
    results: list[Mutant] = []
    runner = list(home.runner)
    if runner[:2] == ["uv", "run"] and "--quiet" not in runner:
        runner[2:2] = ["--quiet"]
    try:
        for mutant, mutated in candidates:
            tests = by_line.get(mutant.line, [])
            mutant.tests = tests[:12]
            if not tests:
                mutant.status = "no coverage"
                results.append(mutant)
                continue
            src.write_text(mutated, encoding="utf-8")
            try:
                run = subprocess.run(
                    [*runner, *tests[:12]],
                    cwd=cwd,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=max(60, baseline_s * timeout_factor),
                )
                mutant.status = "survived" if run.returncode == 0 else "killed"
            except subprocess.TimeoutExpired:
                mutant.status = "timeout"
            finally:
                src.write_text(original, encoding="utf-8")
            results.append(mutant)
    finally:
        src.write_text(original, encoding="utf-8")
    return results, f"baseline {baseline_s:.0f}s on {tests_path}, shared by every changed file under it"


def run_node_mutants(root: Path, home: TestHome, rel: str, lines: set[int], budget: int) -> tuple[list[Mutant], str]:
    """Each line-level fault against the test file beside the code, run from the repository root."""
    src = root / rel
    test_file = root / home.tests
    candidates = node_mutants(src, rel, lines)[:budget]
    if not candidates:
        return [], "no mutable construct on the changed lines"
    if not test_file.is_file():
        for m, _ in candidates:
            m.status = "no coverage"
            m.detail = f"no test beside it ({home.tests})"
        return [m for m, _ in candidates], f"no test file at {home.tests}"
    cmd = [c for c in home.runner if not c.startswith("<")] + [home.tests]
    original = src.read_text(encoding="utf-8")
    results = []
    try:
        for mutant, mutated in candidates:
            src.write_text(mutated, encoding="utf-8")
            mutant.tests = [home.tests]
            try:
                run = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False, timeout=120)
                mutant.status = "survived" if run.returncode == 0 else "killed"
            except subprocess.TimeoutExpired:
                mutant.status = "timeout"
            finally:
                src.write_text(original, encoding="utf-8")
            results.append(mutant)
    finally:
        src.write_text(original, encoding="utf-8")
    return results, " ".join(cmd)


# ----------------------------------------------------------------------------------------------- the audit


def is_test_file(profile: Profile, rel: str) -> bool:
    from review_context import layer_of  # noqa: PLC0415

    row = layer_of(profile, rel)
    return bool(row and plain(row["Layer"]).startswith("tests"))


def related_test_files(root: Path, profile: Profile, code_files: list[str]) -> list[str]:
    out: set[str] = set()
    for rel in code_files:
        home = test_home(profile, rel)
        if not home:
            continue
        target = root / home.tests
        if target.is_dir():
            out.update(str(p.relative_to(root)) for p in target.rglob("test_*.py"))
            out.update(str(p.relative_to(root)) for p in target.rglob("*.test.ts"))
        elif target.is_file():
            out.add(str(target.relative_to(root)))
    return sorted(out)


def audit(
    profile: Profile,
    base: str,
    *,
    paths: list[str] | None,
    design: str | None,
    mutate: bool,
    budget: int,
    timeout_factor: float,
) -> dict[str, object]:
    root = profile.root
    changed = changed_lines(root, base, paths)
    test_files = [p for p in changed if is_test_file(profile, p)]
    code_files = [
        p for p in changed if p not in test_files and p.endswith((".py", ".ts", ".tsx")) and test_home(profile, p)
    ]
    weak, timing, duplicates = static_audit(root, test_files)
    related = related_test_files(root, profile, code_files)
    modes = design_failure_modes(root / design) if design else []
    uncovered = uncovered_failure_modes(root, modes, sorted(set(test_files) | set(related))) if modes else []
    mutants: list[Mutant] = []
    notes: list[str] = []
    if mutate and code_files:
        env = None
        try:
            for rel in code_files:
                home = test_home(profile, rel)
                assert home is not None
                if home.kind == "python":
                    if env is None:
                        env = test_database(profile, root)
                    found, note = run_python_mutants(
                        root, home, rel, changed[rel], env=env, budget=budget, timeout_factor=timeout_factor
                    )
                else:
                    found, note = run_node_mutants(root, home, rel, changed[rel], budget)
                mutants += found
                notes.append(f"{rel}: {note}")
        finally:
            drop_baselines()
    elif mutate:
        notes.append("no changed code file maps to a tests folder in the profile")
    counts = Counter(m.status for m in mutants)
    valid = counts["killed"] + counts["survived"]
    return {
        "base": base,
        "changed_files": sorted(changed),
        "code_files": code_files,
        "test_files": test_files,
        "related_test_files": related,
        "mutation": {
            "score": round(100 * counts["killed"] / valid) if valid else None,
            "killed": counts["killed"],
            "survived": counts["survived"],
            "no_coverage": counts["no coverage"],
            "timeout": counts["timeout"],
            "mutants": [asdict(m) for m in mutants],
            "notes": notes,
        },
        "worth_deleting": [asdict(f) for f in weak + duplicates],
        "timing": [asdict(f) for f in timing],
        "failure_modes": {"design": design, "listed": len(modes), "uncovered": uncovered},
    }


def markdown(a: dict[str, object]) -> str:
    m = a["mutation"]  # type: ignore[assignment]
    lines = [f"# Test audit since {a['base']}", ""]
    score = m["score"]  # type: ignore[index]
    lines += ["## Effectiveness on changed lines", ""]
    if score is None:
        lines.append(f"- mutation score: not measured ({'; '.join(m['notes']) or 'no mutants ran'})")  # type: ignore[index]
    else:
        lines.append(
            f"- mutation score: {score}% (killed {m['killed']}, survived {m['survived']}; "
            f"no coverage {m['no_coverage']}, timeout {m['timeout']})"
        )  # type: ignore[index]
        for n in m["notes"]:  # type: ignore[index]
            lines.append(f"- {n}")
    survivors = [x for x in m["mutants"] if x["status"] in ("survived", "no coverage", "timeout")]  # type: ignore[index]
    if survivors:
        lines += ["", "| Status | Where | Fault | Tests that reached the line |", "|---|---|---|---|"]
        lines += [
            f"| {x['status']} | {x['file']}:{x['line']} | {x['change']} | "
            f"{', '.join(t.split('::')[-1] for t in x['tests'][:3]) or '-'} |"
            for x in survivors
        ]
    lines += ["", "## Failure modes in the design with no test", ""]
    fm = a["failure_modes"]  # type: ignore[assignment]
    if not fm["design"]:  # type: ignore[index]
        lines.append("- no design page given (--design)")
    elif not fm["uncovered"]:  # type: ignore[index]
        lines.append(f"- every one of the {fm['listed']} listed rows has a test that names it")  # type: ignore[index]
    else:
        lines += [f"- {u['failure_mode']} (looked for {u['looked_for']})" for u in fm["uncovered"]]  # type: ignore[index]
    lines += ["", "## Tests worth deleting", ""]
    lines += [f"- {f['file']}:{f['line']} {f['name']}: {f['reason']}" for f in a["worth_deleting"]] or [
        "- none found in the changed test files"
    ]  # type: ignore[index]
    lines += ["", "## Timing", ""]
    lines += [f"- {f['file']}:{f['line']} {f['name']}: {f['reason']}" for f in a["timing"]] or [
        "- no fixed waits in the changed test files"
    ]  # type: ignore[index]
    lines += [
        "",
        f"Changed: {len(a['changed_files'])} files; code audited: {', '.join(a['code_files']) or 'none'}; "
        f"test files read: {len(a['test_files'])} changed, {len(a['related_test_files'])} related.",
    ]  # type: ignore[arg-type]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------------------------- self-test

FIXTURE_CODE = '''"""A fixture module."""


def allowed(role: str, count: int) -> bool:
    """Whether a role may see `count` items."""
    if role == "admin" and count >= 0:
        return True
    return count < 3


def label(n: int) -> str:
    return "item" + ("s" if n != 1 else "")
'''

FIXTURE_TESTS = """import time

from fixture_pkg.mod import allowed, label


def test_admin_is_allowed():
    assert allowed("admin", 5) is True


def test_member_limit():
    assert allowed("member", 2) is True
    assert allowed("member", 3) is False


def test_plural():
    assert label(1) == "item"
    assert label(2) == "items"


def test_nothing_checked():
    allowed("admin", 1)


def test_tautology():
    assert 1 == 1


def test_sleepy():
    time.sleep(0.01)
    assert label(2) == "items"


def test_sleepy_twin():
    time.sleep(0.01)
    assert label(2) == "items"
"""

FIXTURE_PROFILE = """# Fixture profile

## Layers

| Layer | Paths | Read | Check |
|---|---|---|---|
| tests-python | `pkg/tests/**` | - | - |
| package | `pkg/src/**` | - | - |

## Tests

| Code | Tests | Runner (from the code's folder) | Needs |
|---|---|---|---|
| `pkg/src/<module>/**` | `pkg/tests/` | `uv run --no-project --with pytest pytest -q -x -p no:cacheprovider` | - |

| Test database | Value |
|---|---|
| URL template | `sqlite:///<name>` |
| Name for an audit run | `audit` |
"""

FIXTURE_DESIGN = """# Design

## Acceptance criteria and tests

| Failure mode | Layer | Test |
|---|---|---|
| An admin is refused | unit | `test_admin_is_allowed` |
| A member sees past the limit | unit | `test_member_limit` |
| A retired role still sees items | unit | `test_retired_role_is_refused` |
"""


def self_test() -> bool:
    """The static rules and the mutator on a fixture package, run in a temporary git repository."""
    from project_profile import parse  # noqa: PLC0415

    tmp = Path(tempfile.mkdtemp(prefix="ops-audit-selftest-"))
    try:
        (tmp / "pkg/src/fixture_pkg").mkdir(parents=True)
        (tmp / "pkg/tests").mkdir(parents=True)
        (tmp / "pkg/src/fixture_pkg/__init__.py").write_text("")
        (tmp / "pkg/src/fixture_pkg/mod.py").write_text(FIXTURE_CODE)
        (tmp / "pkg/tests/test_mod.py").write_text(FIXTURE_TESTS)
        (tmp / "pkg/tests/conftest.py").write_text(
            "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parents[1] / 'src'))\n"
        )
        (tmp / "design.md").write_text(FIXTURE_DESIGN)
        profile = parse(FIXTURE_PROFILE, tmp / "profile.md", tmp)
        rel_code, rel_tests = "pkg/src/fixture_pkg/mod.py", "pkg/tests/test_mod.py"
        weak, timing, duplicates = static_audit(tmp, [rel_tests])
        reasons = {f.name: f.reason for f in weak}
        uncovered = uncovered_failure_modes(tmp, design_failure_modes(tmp / "design.md"), [rel_tests])
        lines = set(range(1, FIXTURE_CODE.count("\n") + 2))
        home = test_home(profile, rel_code)
        assert home is not None, "the fixture profile maps the code to its tests"
        mutants, note = run_python_mutants(
            tmp, home, rel_code, lines, env=dict(os.environ), budget=40, timeout_factor=5.0
        )
        statuses = Counter(m.status for m in mutants)
        plural_survivor = any(m.status == "survived" and m.line == 12 for m in mutants)
        # Remove every test that calls `label` and the same faults must now go unkilled: the measure can go down.
        weak_tests = re.sub(r"\n\ndef test_(plural|sleepy|sleepy_twin)\(\):\n(?:    .*\n)+", "\n", FIXTURE_TESTS + "\n")
        (tmp / rel_tests).write_text(weak_tests)
        drop_baselines()
        weaker, weaker_note = run_python_mutants(
            tmp, home, rel_code, {12}, env=dict(os.environ), budget=40, timeout_factor=5.0
        )
        cases = [
            (
                "a test with no assertion is worth deleting",
                reasons.get("test_nothing_checked", "").startswith("no assertion"),
            ),
            ("a tautology is worth deleting", "always true" in reasons.get("test_tautology", "")),
            ("a real test is not flagged", "test_member_limit" not in reasons and "test_plural" not in reasons),
            ("a fixed sleep is a timing smell", any(f.name == "test_sleepy" for f in timing)),
            ("two tests with the same body are a duplicate", any(f.name == "test_sleepy_twin" for f in duplicates)),
            (
                "a failure mode whose test does not exist is uncovered",
                [u["looked_for"] for u in uncovered] == ["test_retired_role_is_refused"],
            ),
            ("the baseline ran with coverage contexts", note.startswith("baseline"), note),
            ("faults on tested lines are killed", statuses["killed"] >= 4, dict(statuses)),
            (
                "the fault `>= 0` → `> 0` on the admin branch survives: no test gives an admin zero items",
                any(m.status == "survived" and m.change == ">= → >" for m in mutants),
                [(m.line, m.change, m.status) for m in mutants],
            ),
            ("a fault on the plural line is killed while its test exists", not plural_survivor),
            (
                "the same fault survives once its test is gone",
                all(m.status in ("survived", "no coverage") for m in weaker) and weaker,
                [(m.change, m.status) for m in weaker] or weaker_note,
            ),
        ]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for case in cases:
        name, ok = case[0], case[1]
        print(f"{'PASS' if ok else 'FAIL'} {name}{'' if ok or len(case) < 3 else f': {case[2]}'}")
    return all(c[1] for c in cases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--profile", help="the profile file (default: OPS_AGENT_PROFILE or .claude/project-profile.md)")
    parser.add_argument("--paths", nargs="*", help="limit the audit to these changed files")
    parser.add_argument("--design", help="the design page whose acceptance rows are checked for a test")
    parser.add_argument("--max-mutants", type=int, default=60, help="faults per changed file")
    parser.add_argument("--timeout-factor", type=float, default=3.0, help="a mutant's run may take this many baselines")
    parser.add_argument("--no-mutate", action="store_true", help="static checks and failure modes only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", help="write the report to this file as well")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return 0 if self_test() else 1
    profile = load(args.profile)
    a = audit(
        profile,
        args.base,
        paths=args.paths,
        design=args.design,
        mutate=not args.no_mutate,
        budget=args.max_mutants,
        timeout_factor=args.timeout_factor,
    )
    text = json.dumps(a, indent=1) if args.json else markdown(a)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
