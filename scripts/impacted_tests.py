#!/usr/bin/env python3
"""Picks the test files a change can affect and runs only those, printing what it picked and why.

  make test-impacted BASE=origin/main          # run the picks
  make test-impacted BASE=origin/main PLAN=1   # print the picks only

The pick, by changed file:
- a test file: itself;
- a Python module under packages/*/src or services/*/src: every test file that imports that module (an import map read
  from the test files' own import lines, direct imports only), plus tests/test_<module>*.py in the same member; when
  neither exists, the member's own tests;
- any other file inside a Python member (migrations, seed, openapi.json): that member's whole tests folder;
- a script in scripts/: scripts/tests/test_<script>.py and the tests that import it;
- a console file: the .test.ts beside it; packages/usecase-runner: that package's own tests.
A change to the root uv.lock, pyproject.toml, Makefile or make/ can affect everything, so it is reported and left to the
full check (`make test`); the other picks still run. Documentation is skipped.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_FILES = ("uv.lock", "pyproject.toml", "Makefile", "package.json", "pnpm-lock.yaml")


def changed_files(base: str) -> list[str]:
    """Files changed since the merge base with `base`, working tree included, plus untracked files."""
    mb = subprocess.run(["git", "merge-base", base, "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
    tracked = _git("diff", "--name-only", mb.stdout.strip())
    return sorted({*tracked, *_git("ls-files", "--others", "--exclude-standard")})


def _git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def member_of(path: str) -> str | None:
    """`packages/<x>` or `services/<x>` for a file inside one, else None."""
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) > 2 and parts[0] in ("packages", "services") else None


def module_of(path: str) -> str | None:
    """Dotted module name for src/<pkg>/.../x.py ("ops_store.audit"); the package itself for __init__.py."""
    m = re.match(r"(?:packages|services)/[^/]+/src/(.+)\.py$", path)
    if not m:
        return None
    dotted = m[1].replace("/", ".")
    return dotted.removesuffix(".__init__")


def python_tests(root: Path = ROOT) -> list[str]:
    found: list[str] = []
    for top in ("packages", "services", "scripts/tests"):
        base = root / top
        if base.is_dir():
            found += [
                str(p.relative_to(root))
                for p in base.rglob("test_*.py")
                if not {".venv", "node_modules"} & set(p.parts)
            ]
    return sorted(found)


def importers(module: str, tests: dict[str, str]) -> list[str]:
    """Test files with an import line for `module`, or `from <parent> import <leaf>`."""
    full = re.compile(rf"^\s*(?:from|import)\s+{re.escape(module)}(?:\s|$|\.|,)", re.MULTILINE)
    parent, _, leaf = module.rpartition(".")
    via_parent = (
        re.compile(rf"^\s*from\s+{re.escape(parent)}\s+import\s+[^\n]*\b{re.escape(leaf)}\b", re.MULTILINE)
        if parent
        else None
    )
    return [t for t, text in tests.items() if full.search(text) or (via_parent and via_parent.search(text))]


def pick(changed: list[str], root: Path = ROOT) -> tuple[dict[str, list[str]], list[tuple[str, str]], list[str]]:
    """(python tests by reason, console/package node tests as (cwd, file), notes)."""
    all_tests = python_tests(root)
    text = {t: (root / t).read_text(encoding="utf-8", errors="replace") for t in all_tests}
    py: dict[str, list[str]] = {}
    node: list[tuple[str, str]] = []
    notes: list[str] = []

    def add(test: str, why: str) -> None:
        py.setdefault(test, []).append(why)

    for f in changed:
        if f in BUILD_FILES or f.startswith("make/"):
            notes.append(f"{f}: shared build file, can affect everything; run `make test` for the full check")
            continue
        if f.endswith(".md") or f.startswith("docs/"):
            continue
        if f in text:
            add(f, "changed itself")
            continue
        if f.startswith("scripts/") and f.endswith(".py"):
            stem = Path(f).stem
            same = f"scripts/tests/test_{stem.replace('-', '_')}.py"
            if same in text:
                add(same, f"tests {f}")
            for t in importers(stem.replace("-", "_"), text):
                add(t, f"imports {stem}")
            continue
        if f.startswith("apps/console/src/") and f.endswith((".ts", ".tsx")):
            beside = re.sub(r"\.tsx?$", ".test.ts", f)
            if f.endswith(".test.ts"):
                node.append(("apps/console", f.removeprefix("apps/console/")))
            elif (root / beside).is_file():
                node.append(("apps/console", beside.removeprefix("apps/console/")))
            else:
                notes.append(f"{f}: no test beside it, nothing picked")
            continue
        if f.startswith("packages/usecase-runner/"):
            if (root / "packages/usecase-runner").is_dir() and ("packages/usecase-runner", "src/*.test.ts") not in node:
                node.append(("packages/usecase-runner", "src/*.test.ts"))
            continue
        member = member_of(f)
        if member is None:
            continue
        mod = module_of(f)
        if mod is not None:
            leaf = f"test_{mod.rsplit('.', 1)[-1]}"
            hits = importers(mod, text)
            named = [t for t in all_tests if t.startswith(member + "/") and Path(t).name.startswith(leaf)]
            for t in hits:
                add(t, f"imports {mod}")
            for t in named:
                add(t, f"named for {mod}")
            if not hits and not named:
                # Callers reach the module through the package's own names (`from pkg import X`), which an import
                # line map cannot see; the member's own tests are the nearest safe pick.
                own = [t for t in all_tests if t.startswith(member + "/")]
                for t in own:
                    add(t, f"no test imports {mod}; {member}'s own tests")
                if not own:
                    notes.append(f"{f}: no test imports {mod} and {member} has no tests, nothing picked")
        elif member and (root / member / "tests").is_dir():
            for t in all_tests:
                if t.startswith(member + "/tests/"):
                    add(t, f"{f} is in {member}, whole package tests")
    return py, node, notes


def commands(py: dict[str, list[str]], node: list[tuple[str, str]]) -> list[tuple[list[str], Path]]:
    """One command per member for Python (make test PKG= T=, which honours T), one per node folder."""
    by_member: dict[str, list[str]] = {}
    for t in sorted(py):
        by_member.setdefault(member_of(t) or ".", []).append(t)
    out: list[tuple[list[str], Path]] = []
    for member, files in by_member.items():
        if member == ".":
            out.append((["uv", "run", "pytest", "-q", *files], ROOT))
        else:
            rel = " ".join(f.removeprefix(member + "/") for f in files)
            out.append((["make", "-s", "test", f"PKG={member}", f"T={rel}"], ROOT))
    grouped: dict[str, list[str]] = {}
    for cwd, f in node:
        grouped.setdefault(cwd, []).append(f)
    for cwd, files in grouped.items():
        out.append((["node", "--test", *sorted(set(files))], ROOT / cwd))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--list", action="store_true", help="print the picks and stop")
    ap.add_argument("--files", nargs="*", help="use these changed files instead of git (for checks)")
    args = ap.parse_args(argv)
    changed = args.files if args.files is not None else changed_files(args.base)
    py, node, notes = pick(changed)
    print(f"test-impacted: {len(changed)} changed file(s) since {args.base}")
    # Tests picked for one identical reason print as one line, so a whole-package pick stays readable.
    by_reason: dict[str, list[str]] = {}
    for t, why in sorted(py.items()):
        by_reason.setdefault("; ".join(dict.fromkeys(why)), []).append(t)
    for why, tests in by_reason.items():
        shown = tests[0] if len(tests) == 1 else f"{len(tests)} files in {member_of(tests[0]) or 'scripts/tests'}"
        print(f"  pick {shown}  ({why})")
    for cwd, f in node:
        print(f"  pick {cwd}/{f}  (console/package test)")
    for n in notes:
        print(f"  note {n}")
    cmds = commands(py, node)
    if not cmds:
        print("test-impacted: nothing to run")
        return 0
    if args.list:
        return 0
    failed = 0
    for cmd, cwd in cmds:
        print(f"$ {' '.join(cmd)}", flush=True)
        failed |= subprocess.run(cmd, cwd=cwd, check=False).returncode != 0
    print("test-impacted: " + ("FAILED" if failed else "green"))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
