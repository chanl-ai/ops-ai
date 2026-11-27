#!/usr/bin/env python3
"""A use case that needs something a hosted runner lacks says so in its registry status, with an owner and an expiry.

The needs, and the status word that declares each (docs/usecases/README.md, the status column):
  manual         the script runs an Example's setup.py or reads OPS_BASE_URL: a standing `make up` stack
  needs-plugins  it reads OPS_PLUGINS_REPO or PLUGINS_REPO, itself or through a module of docs/usecases/lib: the
                 sibling ops-ai-plugins checkout (detection is packages/usecase-runner/src/run.ts, called here)
  needs-key      it reads OPENAI_API_KEY or ANTHROPIC_API_KEY from the environment: a real provider key
A script that needs one without its word fails here. A row with one of the words, or a row in a page's Gaps table, also
carries `owner=<who>` and `until=<YYYY-MM-DD>` (rows) or Owner and Until cells (gaps), and fails here once the date has
passed, so nothing stays skipped without someone to end it. `--self-test` plants each case.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ci_usecases import ROW  # noqa: E402  (the registry row shape has one owner)

ROOT = HERE.parent
WORDS = ("manual", "needs-plugins", "needs-key")
NEEDS_WHAT = {"manual": "standing stack", "needs-plugins": "plugins checkout", "needs-key": "real provider key"}
KEY = re.compile(r"""(?:environ(?:\.get)?[\[(]\s*|getenv\(\s*|process\.env\.)["']?(?:OPENAI|ANTHROPIC)_API_KEY""")
# A script runs an Example's setup (a path under examples/ and setup.py anywhere in the file) or reads the stack's URL.
STACK = (re.compile(r"OPS_BASE_URL"), re.compile(r"examples/"), re.compile(r"setup\.py"))
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def needs_of(text: str, plugins: bool) -> set[str]:
    found = set()
    if STACK[0].search(text) or (STACK[1].search(text) and STACK[2].search(text)):
        found.add("manual")
    if plugins:
        found.add("needs-plugins")
    if KEY.search(text):
        found.add("needs-key")
    return found


def plugin_users(paths: list[Path]) -> set[str]:
    """The scripts the runner itself would stop for a missing plugins checkout: one owner of that rule (run.ts)."""
    if not paths:
        return set()
    js = (
        "import { scriptNeedsPlugins } from './packages/usecase-runner/src/run.ts';"
        "const files = JSON.parse(process.argv[1]);"
        "console.log(JSON.stringify(files.filter((f) => scriptNeedsPlugins(f))));"
    )
    done = subprocess.run(
        ["node", "--input-type=module", "-e", js, json.dumps([str(p) for p in paths])],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return set(json.loads(done.stdout))


def status_cells(registry: str) -> dict[str, list[str]]:
    return {m.group(1): m.group(3).split() for line in registry.splitlines() if (m := ROW.match(line))}


def row_misses(registry: str, today: str) -> list[str]:
    misses = []
    for uc, words in sorted(status_cells(registry).items()):
        if not any(w.lower() in WORDS for w in words):
            continue
        tags = dict(w.split("=", 1) for w in words if "=" in w)
        if not tags.get("owner"):
            misses.append(f"{uc} has a need status without owner=<who>")
        if not DATE.match(tags.get("until", "")):
            misses.append(f"{uc} has a need status without until=<YYYY-MM-DD>")
        elif tags["until"] < today:
            misses.append(f"{uc} need status expired on {tags['until']}: fix the use case or renew it")
    return misses


def _cell(head: list[str], cells: list[str], name: str) -> str:
    return cells[head.index(name)] if name in head and head.index(name) < len(cells) else ""


def gap_misses(pages: dict[str, str], today: str) -> list[str]:
    misses = []
    for path, text in sorted(pages.items()):
        head: list[str] = []
        in_gaps = False
        for n, line in enumerate(text.splitlines(), 1):
            if line.startswith("## "):
                in_gaps = line.strip().lower() == "## gaps"
                continue
            if not (in_gaps and line.startswith("|")):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if cells and cells[0] == "Product fix":
                head = cells
                continue
            if not cells or all(re.fullmatch(r"-*", c) for c in cells):
                continue
            owner, until = (_cell(head, cells, n) for n in ("Owner", "Until"))
            if not owner or not DATE.match(until):
                misses.append(f"{path}:{n} gap row has no Owner and Until date, so its SKIP would never end")
            elif until < today:
                misses.append(f"{path}:{n} gap expired on {until}")
    return misses


def undeclared(registry: str, scripts: dict[str, tuple[str, bool]]) -> list[str]:
    status = {uc: {w.lower() for w in words} for uc, words in status_cells(registry).items()}
    misses = []
    for uc, (text, plugins) in sorted(scripts.items()):
        for word in sorted(needs_of(text, plugins) - status.get(uc, set())):
            misses.append(f"{uc} needs a {NEEDS_WHAT[word]} but its registry status lacks `{word}`")
    return misses


PAGE_ID = re.compile(r"^\| Id \| `(uc-[a-z0-9-]+)` \|", re.M)


def scripts_by_id(root: Path) -> dict[str, tuple[str, bool]]:
    # A use case with a page runs the page for its sdk and cli layers (page.ts findPage), never those layers' scripts.
    paged = {m for p in (root / "docs/usecases").glob("*/*.md") for m in PAGE_ID.findall(p.read_text(encoding="utf-8"))}
    files: dict[str, list[Path]] = {}
    for path in sorted((root / "docs/usecases").glob("*/scripts/test-uc-*")):
        m = re.match(r"test-(uc-[a-z0-9]+(?:-[a-z0-9]+)*?)-(api|sdk|cli|ui)\.", path.name)
        if m and not (m.group(1) in paged and m.group(2) in ("sdk", "cli")):
            files.setdefault(m.group(1), []).append(path)
    users = plugin_users([p for ps in files.values() for p in ps])
    return {
        uc: ("\n".join(p.read_text(encoding="utf-8") for p in ps), any(str(p) in users for p in ps))
        for uc, ps in files.items()
    }


def run(root: Path, today: str) -> list[str]:
    registry = (root / "docs/usecases/README.md").read_text(encoding="utf-8")
    pages = {
        str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in sorted((root / "docs/usecases").glob("*/*.md"))
    }
    return row_misses(registry, today) + gap_misses(pages, today) + undeclared(registry, scripts_by_id(root))


def self_test() -> int:
    today = "2026-11-27"
    ok = "owner=ops-release until=2026-12-26"

    def plant(status: str, script: str, gaps: str = "", page_id: bool = False) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs/usecases/lib").mkdir(parents=True)
            (root / "docs/usecases/area/scripts").mkdir(parents=True)
            (root / "docs/usecases/README.md").write_text(f"| uc-1 | area | t | api | {status} |\n")
            (root / "docs/usecases/area/scripts/test-uc-1-sdk.py").write_text(script)
            if page_id:
                (root / "docs/usecases/area/page.md").write_text("| Id | `uc-1` |\n")
            (root / "docs/usecases/lib/shared.py").write_text("import os\nREPO = os.environ['OPS_PLUGINS_REPO']\n")
            if gaps:
                (root / "docs/usecases/area/gaps.md").write_text(f"## Gaps\n\n{gaps}\n")
            return run(root, today)

    gap_head = (
        "| Product fix | Step | Tab | What is missing | Where | Open since | Owner | Until |\n" + "|---|" * 8 + "\n"
    )
    cases = [
        ("plugins read directly, undeclared", plant("current", "os.environ.get('OPS_PLUGINS_REPO')"), 1),
        ("plugins read through a library, undeclared", plant("current", "import shared\n"), 1),
        ("plugins declared with owner and date", plant(f"current needs-plugins {ok}", "import shared\n"), 0),
        ("plugins declared without owner and date", plant("current needs-plugins", "import shared\n"), 2),
        ("declared but expired", plant("current needs-plugins owner=a until=2026-11-26", "import shared\n"), 1),
        ("key read, undeclared", plant("current", "os.environ.get('OPENAI_API_KEY')"), 1),
        ("key deleted, not read", plant("current", "env.pop('OPENAI_API_KEY', None)"), 0),
        (
            "example setup on another line, undeclared",
            plant("current", "p = 'examples/chat/01'\nrun(p + '/setup.py')\n"),
            1,
        ),
        ("stack declared", plant(f"manual {ok}", "x = os.environ['OPS_BASE_URL']"), 0),
        ("script with no need", plant("current", "print('hi')"), 0),
        ("paged use case's sdk script is not run", plant("current", "os.environ['OPS_BASE_URL']", page_id=True), 0),
        (
            "gap row with owner and date",
            plant(
                "current", "print('hi')", gap_head + "| a | All | Go | b | c | 2026-11-12 | ops-release | 2026-12-26 |"
            ),
            0,
        ),
        (
            "gap row without owner and date",
            plant("current", "print('hi')", gap_head + "| a | All | Go | b | c | 2026-11-12 |  |  |"),
            1,
        ),
    ]
    wrong = [f"{name}: wanted {n}, got {got}" for name, got, n in cases if len(got) != n]
    if wrong:
        print("check_usecase_needs self-test failed:\n  " + "\n  ".join(wrong), file=sys.stderr)
        return 1
    print(f"check_usecase_needs self-test: {len(cases)} cases")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    misses = run(ROOT, date.today().isoformat())
    for m in misses:
        print(m, file=sys.stderr)
    print(f"check_usecase_needs: {len(misses)} problems")
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
