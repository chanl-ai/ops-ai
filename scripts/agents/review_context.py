"""One compact bundle a reviewer reads before the diff, so the review spends its attention on judgement.

For the commits since a base, the bundle holds: the diff stat; the changed files grouped by the profile's layers with
the documents each layer says to read; the tests added or changed and how many cases they add; the public surface the
diff adds (routes, models, migrations, console routes and contracts, SDK files); the commit subjects; and the result
of the checks the profile lists (leak scan, public paths, docs, lint), each run on the changed files only. The profile
(`.claude/project-profile.md`, sections "Layers", "Public surface" and "Checks a review runs first") owns every path
and pattern here; this script owns none.

  python3 scripts/agents/review_context.py --base origin/main            markdown to stdout
  python3 scripts/agents/review_context.py --base origin/main --json     the same facts as JSON
  python3 scripts/agents/review_context.py --self-test                   the grouping and surface rules on fixtures
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_profile import Profile, load, plain

TEST_LAYERS = ("tests-python", "tests-console")
# A new test case on an added line, per language.
TEST_CASE = re.compile(r"^\+\s*(?:async\s+)?def\s+test_\w+|^\+\s*(?:test|it)\(\s*['\"`]|^\+\s*check\(\s*['\"`]")
# The "Public surface" column that holds a regex to run on added lines (its heading starts with this); the "Files"
# column either names globs or a path rule in words ("path contains it", "path ends with it", "path matches").
PATTERN_COLUMN_PREFIX = "Pattern"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def globs(cell: str) -> list[str]:
    """The globs in a profile cell: comma separated, backticks removed."""
    return [g.strip() for g in plain(cell).split(",") if g.strip()]


def matches(path: str, pattern: str) -> bool:
    """fnmatch with `**` crossing folders and `*` staying inside one."""
    regex = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.fullmatch(regex, path) is not None


def layer_of(profile: Profile, path: str) -> dict[str, str] | None:
    """The first "Layers" row whose paths match."""
    for row in profile.table("Layers", "Paths"):
        if any(matches(path, g) for g in globs(row["Paths"])):
            return row
    return None


def group_by_layer(profile: Profile, paths: list[str]) -> dict[str, dict[str, object]]:
    groups: dict[str, dict[str, object]] = {}
    for path in paths:
        row = layer_of(profile, path)
        name = plain(row["Layer"]) if row else "unmapped"
        group = groups.setdefault(
            name, {"files": [], "read": plain(row["Read"]) if row else "", "check": plain(row["Check"]) if row else ""}
        )
        group["files"].append(path)  # type: ignore[union-attr]
    return groups


def added_lines(diff: str) -> dict[str, list[tuple[int, str]]]:
    """Added lines per file, with their new line numbers, from a unified diff."""
    out: dict[str, list[tuple[int, str]]] = {}
    path = ""
    line_no = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            path = path[2:] if path.startswith("b/") else path
            out.setdefault(path, [])
        elif raw.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", raw)
            line_no = int(m.group(1)) if m else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            out.setdefault(path, []).append((line_no, raw[1:]))
            line_no += 1
        elif not raw.startswith("-") and not raw.startswith("\\"):
            line_no += 1
    return out


def public_surface(profile: Profile, added: dict[str, list[tuple[int, str]]]) -> list[dict[str, str]]:
    """Every added route, model, migration, console route or contract, and SDK file, from the profile's rules."""
    found: list[dict[str, str]] = []
    for row in profile.table("Public surface", "Surface"):
        surface = plain(row["Surface"])
        column = next(c for c in row if c.startswith(PATTERN_COLUMN_PREFIX))
        pattern = row[column].strip().strip("`")
        files = plain(row["Files"])
        path_rule = files.startswith("path ")
        if path_rule:
            for path in added:
                if (
                    (files.startswith("path contains") and pattern in path)
                    or (files.startswith("path ends with") and path.endswith(pattern))
                    or (files.startswith("path matches") and any(matches(path, g) for g in [pattern]))
                ):
                    if "outside" in files and files.split("outside")[-1].strip().strip("`") in path:
                        continue
                    found.append({"surface": surface, "where": path, "what": path.rsplit("/", 1)[-1]})
            continue
        regex = re.compile(pattern)
        file_globs = globs(files)
        for path, lines in added.items():
            if not any(matches(path, g) for g in file_globs):
                continue
            for no, text in lines:
                m = regex.search(text)
                if m:
                    what = " ".join(g for g in m.groups() if g) or text.strip()
                    found.append({"surface": surface, "where": f"{path}:{no}", "what": what})
    return found


def tests_changed(
    profile: Profile, paths: list[str], added: dict[str, list[tuple[int, str]]]
) -> list[dict[str, object]]:
    out = []
    for path in paths:
        row = layer_of(profile, path)
        if row and plain(row["Layer"]) in TEST_LAYERS:
            cases = sum(1 for _, text in added.get(path, []) if TEST_CASE.match("+" + text))
            out.append({"file": path, "cases_added": cases})
    return out


def run_checks(profile: Profile, base: str, paths: list[str]) -> list[dict[str, str]]:
    """The profile's first checks, each on the changed files it applies to; a missing tool is reported, not hidden."""
    py = [p for p in paths if p.endswith(".py") and (profile.root / p).is_file()]
    md = [p for p in paths if p.endswith(".md") and (profile.root / p).is_file()]
    present = [p for p in paths if (profile.root / p).is_file()]
    results = []
    for row in profile.table("Checks a review runs first", "Check"):
        name = plain(row["Check"])
        command = plain(row["Command"])
        if "<files>" in command:
            files = py if "ruff" in command else md if "check-docs" in command else present
            if not files:
                results.append({"check": name, "result": "skipped: no files it applies to"})
                continue
            commands = [c.strip().replace("<files>", " ".join(files)) for c in command.split(" and ")]
        elif "<base>" in command:
            commands = [command.replace("<base>", base)]
        elif name == "commit message":
            # Already enforced by the commit hook on every commit here; the bundle records that, not a rerun.
            results.append({"check": name, "result": "enforced by the commit hook on each commit"})
            continue
        elif name == "console standards" and not any(p.startswith("apps/") for p in paths):
            results.append({"check": name, "result": "skipped: no console files changed"})
            continue
        else:
            commands = [command]
        for cmd in commands:
            done = subprocess.run(shlex.split(cmd), cwd=profile.root, capture_output=True, text=True, check=False)
            tail = (done.stdout + done.stderr).strip().splitlines()[-3:]
            results.append(
                {
                    "check": name,
                    "result": ("green" if done.returncode == 0 else "RED")
                    + ": "
                    + " | ".join(t.strip() for t in tail)[:300],
                }
            )
    return results


def bundle(profile: Profile, base: str, run: bool = True) -> dict[str, object]:
    root = profile.root
    merge_base = git(root, "merge-base", base, "HEAD").strip()
    paths = [p for p in git(root, "diff", "--name-only", merge_base, "HEAD").splitlines() if p]
    diff = git(root, "diff", "--unified=0", merge_base, "HEAD")
    added = added_lines(diff)
    stat = git(root, "diff", "--stat=100", merge_base, "HEAD").strip().splitlines()
    subjects = [s for s in git(root, "log", "--format=%s", f"{merge_base}..HEAD").splitlines() if s]
    groups = group_by_layer(profile, paths)
    docs_touched = [p for p in paths if p.endswith(".md") or p.startswith("docs/")]
    code_layers = [name for name in groups if name not in (*TEST_LAYERS, "docs", "changelog")]
    return {
        "base": base,
        "merge_base": merge_base[:12],
        "commits": subjects,
        "stat": stat[-1] if stat else "no changes",
        "files": len(paths),
        "layers": groups,
        "tests": tests_changed(profile, paths, added),
        "surface": public_surface(profile, added),
        "docs_touched": docs_touched,
        "code_without_docs": [name for name in code_layers if not docs_touched],
        "checks": run_checks(profile, base, paths) if run else [],
    }


def markdown(b: dict[str, object]) -> str:
    lines = [f"# Review context since {b['base']} ({b['merge_base']})", "", f"{b['stat']}", ""]
    lines += ["## Commits", *[f"- {s}" for s in b["commits"]], ""]  # type: ignore[union-attr]
    lines += ["## Changed files by layer", "", "| Layer | Files | Read first | Check |", "|---|---|---|---|"]
    for name, group in b["layers"].items():  # type: ignore[union-attr]
        files = ", ".join(group["files"])
        lines.append(f"| {name} | {files} | {group['read']} | {group['check']} |")
    tests = b["tests"]
    lines += ["", "## Tests added or changed", ""]
    lines += [f"- {t['file']}: {t['cases_added']} case(s) added" for t in tests] or ["- none"]  # type: ignore[index]
    lines += ["", "## New public surface", ""]
    lines += [f"- {s['surface']}: {s['what']} ({s['where']})" for s in b["surface"]] or ["- none"]  # type: ignore[index]
    lines += ["", "## Docs", ""]
    lines += [f"- touched: {', '.join(b['docs_touched']) or 'none'}"]  # type: ignore[arg-type]
    if b["code_without_docs"]:
        lines.append(
            f"- code changed in {', '.join(b['code_without_docs'])} with no doc or README change: "
            "check the layer's Read column"
        )  # type: ignore[arg-type]
    lines += ["", "## Checks", ""]
    lines += [f"- {c['check']}: {c['result']}" for c in b["checks"]] or ["- not run"]  # type: ignore[index]
    return "\n".join(lines) + "\n"


FIXTURE_PROFILE = """# Fixture profile

## Layers

| Layer | Paths | Read | Check |
|---|---|---|---|
| tests-python | `services/*/tests/**` | `CLAUDE.md` | `ruff` |
| service | `services/*/src/**` | `docs/architecture/api.md` | `make test` |
| console | `apps/console/src/**` | `apps/console/CLAUDE.md` | `pnpm verify` |

## Public surface

| Surface | Pattern (Python regex on an added line; a bar inside it is written `\\|`) | Files |
|---|---|---|
| HTTP route | `@router\\.(get\\|post)\\(\\s*["']([^"']+)` | `services/*/src/**/*.py` |
| Migration | `migrations/versions/` | path contains it |
| Console route | `apps/console/src/app/**/page.tsx` | path matches |
"""

FIXTURE_DIFF = """diff --git a/services/kb-service/src/ops_kb/app.py b/services/kb-service/src/ops_kb/app.py
--- a/services/kb-service/src/ops_kb/app.py
+++ b/services/kb-service/src/ops_kb/app.py
@@ -10,0 +11,2 @@
+@router.post("/v1/bases/{id}/rebuild")
+async def rebuild() -> None: ...
diff --git a/services/kb-service/tests/test_rebuild.py b/services/kb-service/tests/test_rebuild.py
--- a/services/kb-service/tests/test_rebuild.py
+++ b/services/kb-service/tests/test_rebuild.py
@@ -0,0 +1,3 @@
+async def test_a_rebuild_frees_its_source() -> None:
+    assert True
+def helper(): ...
diff --git a/services/kb-service/migrations/versions/0009_x.py b/services/kb-service/migrations/versions/0009_x.py
--- /dev/null
+++ b/services/kb-service/migrations/versions/0009_x.py
@@ -0,0 +1 @@
+revision = "0009"
diff --git a/apps/console/src/app/knowledge/page.tsx b/apps/console/src/app/knowledge/page.tsx
--- /dev/null
+++ b/apps/console/src/app/knowledge/page.tsx
@@ -0,0 +1 @@
+export default function Page() {}
"""


def self_test() -> bool:
    """The grouping and surface rules on a fixture diff; each case is a failure mode of the bundle."""
    from project_profile import parse  # noqa: PLC0415

    profile = parse(FIXTURE_PROFILE, Path("fixture.md"), Path("."))
    added = added_lines(FIXTURE_DIFF)
    paths = list(added)
    groups = group_by_layer(profile, paths)
    surface = public_surface(profile, added)
    tests = tests_changed(profile, paths, added)
    kinds = Counter(s["surface"] for s in surface)
    cases = [
        (
            "the service file lands in the service layer",
            groups["service"]["files"] == ["services/kb-service/src/ops_kb/app.py"],
        ),
        (
            "the test file lands in the tests layer, not the service",
            groups["tests-python"]["files"] == ["services/kb-service/tests/test_rebuild.py"],
        ),
        (
            "a file no layer claims is listed as unmapped",
            "unmapped" in groups and "services/kb-service/migrations/versions/0009_x.py" in groups["unmapped"]["files"],
        ),
        (
            "the added route is found with its path",
            any(
                s["surface"] == "HTTP route"
                and s["what"] == "post /v1/bases/{id}/rebuild"
                and s["where"].endswith(":11")
                for s in surface
            ),
        ),
        ("the migration is found by its path", kinds["Migration"] == 1),
        ("the console route is found by its path", kinds["Console route"] == 1),
        (
            "one test case is counted, the helper is not",
            tests == [{"file": "services/kb-service/tests/test_rebuild.py", "cases_added": 1}],
        ),
        (
            "a double-star glob crosses folders and a single star does not",
            matches("a/b/c/d.py", "a/**/d.py") and not matches("a/b/c.py", "a/*.py"),
        ),
    ]
    for name, ok in cases:
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    return all(ok for _, ok in cases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="origin/main", help="the branch or sha the change is measured from")
    parser.add_argument("--profile", help="the profile file (default: OPS_AGENT_PROFILE or .claude/project-profile.md)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of markdown")
    parser.add_argument("--no-checks", action="store_true", help="skip the leak scan, docs and lint runs")
    parser.add_argument("--out", help="write the bundle to this file as well")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return 0 if self_test() else 1
    profile = load(args.profile)
    b = bundle(profile, args.base, run=not args.no_checks)
    text = json.dumps(b, indent=1) if args.json else markdown(b)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
