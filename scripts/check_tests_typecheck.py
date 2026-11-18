"""Strict pyright, with the type errors in test files counted against a baseline that may only fall.

Runs pyright with the arguments given (the same directories and the same per-member configuration a typecheck target
used before, from the same folder) and splits its errors by project: a file's project is its nearest folder with a
`pyproject.toml`, and the file is a test file when a `tests` folder sits between the two. An error anywhere else (`src`,
migrations, scripts) fails the run, as plain pyright did. Test files are compared with
`<project>/tests-typecheck-baseline.txt`, rows `<count> <path from the project>`: a file above its row, or with errors
and no row, fails and is named with its first errors. A project with no file allows none.

A row may only fall. `--update` lowers rows and drops fixed ones, and never adds or raises one. `--seed` writes today's
counts for a project that has no file yet and prints what it wrote; it refuses a project that has one. `--commits` reads
the files' history (scripts/baseline_history.py): a commit that raises a row, adds one or adds a file is a rise that
needs a maintainer's approving review on the pull request.

  uv run python scripts/check_tests_typecheck.py src tests            # from a service folder, as `make typecheck`
  uv run python scripts/check_tests_typecheck.py --pyright "$PYRIGHT" packages
  uv run python scripts/check_tests_typecheck.py --update src tests   # lower the baselines to today's counts
  uv run python scripts/check_tests_typecheck.py --seed src tests     # first file for a project with none
  uv run python scripts/check_tests_typecheck.py --commits | --self-test
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseline_history

ROOT = Path(__file__).resolve().parents[1]
BASELINES_BEGAN = "f2f7893e913d7d10257cf517d3273bc4696e6b18"
BASELINE_NAME = "tests-typecheck-baseline.txt"
PATHSPECS = [f"packages/*/{BASELINE_NAME}", f"services/*/{BASELINE_NAME}"]
SHOWN = 3
HEADER = (
    "# Static type errors in this project's test files, as pyright reports them: `<count> <path from the project>`.\n"
    "# A row may only fall: scripts/check_tests_typecheck.py --update lowers or drops rows and never adds or raises\n"
    "# one. A rise or a new row in a commit needs a maintainer's approving review (scripts/baseline_history.py).\n"
)


@dataclass(frozen=True)
class Error:
    file: Path  # resolved
    line: int
    message: str

    def show(self, cwd: Path) -> str:
        try:
            name = self.file.relative_to(cwd)
        except ValueError:
            name = self.file
        return f"{name}:{self.line}: {(self.message.strip().splitlines() or [''])[0].strip()}"


def project_of(file: Path) -> Path:
    for parent in file.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return file.parent


def test_key(file: Path) -> tuple[Path, str] | None:
    """The project and the path from it for a test file; None for every other file."""
    project = project_of(file)
    rel = file.relative_to(project)
    # Only a `tests` folder directly under the project counts; `src/<pkg>/tests/` holds package code.
    return (project, rel.as_posix()) if rel.parts[0] == "tests" and len(rel.parts) > 1 else None


def read_baseline(path: Path) -> Counter[str] | None:
    return baseline_history.rows(path.read_text()) if path.is_file() else None


def write_baseline(path: Path, counts: Counter[str]) -> None:
    body = "".join(f"{n} {key}\n" for key, n in sorted(counts.items()) if n > 0)
    path.write_text(HEADER + body)


def check(
    errors: list[Error], baselines: dict[Path, Counter[str] | None], cwd: Path
) -> tuple[list[str], dict[Path, Counter[str]]]:
    """The problems and each project's test error counts. Pure: `baselines` holds every project's file (None: none)."""
    problems: list[str] = []
    counts: dict[Path, Counter[str]] = defaultdict(Counter)
    by_file: dict[tuple[Path, str], list[Error]] = defaultdict(list)
    for e in errors:
        key = test_key(e.file)
        if key is None:
            problems.append(e.show(cwd))
            continue
        counts[key[0]][key[1]] += 1
        by_file[key].append(e)
    for (project, rel), found in sorted(by_file.items()):
        allowed = (baselines.get(project) or Counter[str]())[rel]
        if len(found) > allowed:
            listed = "; ".join(e.show(cwd) for e in found[:SHOWN])
            problems.append(
                f"{project.relative_to(cwd) if project.is_relative_to(cwd) else project}/{rel}: "
                f"{len(found)} type errors, {allowed} allowed by {BASELINE_NAME}: {listed}"
            )
    return problems, counts


def lowered(base: Counter[str], now: Counter[str]) -> Counter[str]:
    """Each row at today's count where that is lower; never a row added or raised."""
    return Counter({key: min(n, now[key]) for key, n in base.items() if min(n, now[key]) > 0})


def run_pyright(command: list[str], args: list[str]) -> tuple[list[Error], str] | str:
    out = subprocess.run([*command, "--outputjson", *args], capture_output=True, text=True, check=False)
    try:
        report = json.loads(out.stdout)
    except ValueError:
        return f"pyright did not report (exit {out.returncode}):\n{out.stdout}{out.stderr}"
    if out.returncode > 1:
        return f"pyright failed (exit {out.returncode}):\n{out.stdout[-2000:]}{out.stderr}"
    errors = [
        Error(
            Path(d.get("file") or ".").resolve(), d.get("range", {}).get("start", {}).get("line", 0) + 1, d["message"]
        )
        for d in report.get("generalDiagnostics", [])
        if d.get("severity") == "error"
    ]
    return errors, str(report.get("summary", {}).get("filesAnalyzed", "?"))


def projects_for(cwd: Path, args: list[str], errors: list[Error]) -> set[Path]:
    """Every project the run covers: those with an error and those under each argument, so a baseline whose files are
    all fixed is still read (and lowered by --update)."""
    found = {key[0] for e in errors if (key := test_key(e.file))}
    for arg in [a for a in args if not a.startswith("-")]:
        path = (cwd / arg).resolve()
        found.add(project_of(path / "x"))
        found.update(p.parent.resolve() for p in path.glob(f"*/{BASELINE_NAME}"))
    return found


def typecheck(argv: list[str]) -> int:
    command = shlex.split(argv[argv.index("--pyright") + 1]) if "--pyright" in argv else []
    args = [
        a
        for i, a in enumerate(argv)
        if a not in {"--update", "--seed", "--pyright"} and not (i and argv[i - 1] == "--pyright")
    ]
    if not command:
        command = [found] if (found := shutil.which("pyright")) else ["uv", "run", "pyright"]
    cwd = Path.cwd().resolve()
    result = run_pyright(command, args)
    if isinstance(result, str):
        sys.stderr.write(result + "\n")
        return 1
    errors, analysed = result
    projects = projects_for(cwd, args, errors)
    baselines = {p: read_baseline(p / BASELINE_NAME) for p in projects}
    problems, counts = check(errors, baselines, cwd)
    if "--seed" in argv:
        for project in sorted(projects):
            path = project / BASELINE_NAME
            if baselines[project] is not None:
                sys.stderr.write(f"--seed: {path} exists; it only falls (--update)\n")
                return 1
            if counts.get(project):
                write_baseline(path, counts[project])
                total = sum(counts[project].values())
                sys.stdout.write(f"seeded {path}: {total} errors in {len(counts[project])} test files\n")
        problems = [p for p in problems if "allowed by" not in p]
    elif "--update" in argv:
        for project in sorted(projects):
            base = baselines[project]
            if base is not None and (new := lowered(base, counts.get(project, Counter[str]()))) != base:
                write_baseline(project / BASELINE_NAME, new)
                sys.stdout.write(f"lowered {project / BASELINE_NAME}: {sum(base.values())} -> {sum(new.values())}\n")
    for line in problems:
        sys.stderr.write(line + "\n")
    tests = sum(sum(c.values()) for c in counts.values())
    allowed = sum(sum(b.values()) for b in baselines.values() if b)
    sys.stdout.write(
        f"check_tests_typecheck: {analysed} files, {len(errors) - tests} errors outside tests, "
        f"{tests} in tests ({allowed} allowed by baselines), {len(problems)} problems\n"
    )
    return 1 if problems else 0


def self_test() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        project = root / "services/demo"
        (project / "tests").mkdir(parents=True)
        (project / "pyproject.toml").write_text("")
        write_baseline(project / BASELINE_NAME, Counter({"tests/test_a.py": 2}))

        def errs(name: str, n: int) -> list[Error]:
            return [Error(project / name, i + 1, f"planted {i}") for i in range(n)]

        def run(errors: list[Error]) -> list[str]:
            return check(errors, {project: read_baseline(project / BASELINE_NAME)}, root)[0]

        if run(errs("tests/test_a.py", 2)):
            failures.append("a file at its row was refused")
        if not any("test_a.py: 3 type errors, 2 allowed" in p for p in run(errs("tests/test_a.py", 3))):
            failures.append("a file above its row was accepted")
        if not any("test_b.py: 1 type errors, 0 allowed" in p for p in run(errs("tests/test_b.py", 1))):
            failures.append("a new file with errors was accepted")
        if not run(errs("src/demo/app.py", 1)):
            failures.append("an error outside tests was accepted")
        if lowered(Counter({"tests/test_a.py": 2}), Counter({"tests/test_a.py": 5, "tests/test_b.py": 1})) != Counter(
            {"tests/test_a.py": 2}
        ):
            failures.append("--update raised or added a row")
        nofile = check(errs("tests/test_a.py", 1), {project: None}, root)[0]
        if not nofile:
            failures.append("a project with no file allowed an error")
    print("self-test: FAILED " + "; ".join(failures) if failures else "self-test: test type error rises are refused")
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    if "--commits" in argv:
        missing = baseline_history.problems(ROOT, BASELINES_BEGAN, PATHSPECS)
        sys.stdout.write(
            "\n".join(missing) + "\n" if missing else baseline_history.outcome("check_tests_typecheck") + "\n"
        )
        return 1 if missing else 0
    return typecheck(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
