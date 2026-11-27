#!/usr/bin/env python3
"""A use case that needs something a hosted runner lacks says so in its registry status.

The needs, and the status word that declares each (docs/usecases/README.md, the status column):
  stack    `manual`        the script runs an Example's setup.py or reads OPS_BASE_URL: a standing `make up` stack
  plugins  `needs-plugins` it reads OPS_PLUGINS_REPO or PLUGINS_REPO: the sibling ops-ai-plugins checkout
  key      `needs-key`     it reads OPENAI_API_KEY or ANTHROPIC_API_KEY from the environment: a real provider key
A script that reads one without its word fails here, so a hosted run does not find out first. `--self-test` plants a
script of each kind and fails unless each is caught.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "docs/usecases/README.md"
ROW = re.compile(r"^\|\s*(uc-[a-z0-9]+(?:-[a-z0-9]+)*)\s*\|[^|]*\|[^|]*\|[^|]*\|\s*([^|]*?)\s*\|")
NEEDS = {
    "manual": re.compile(r"""OPS_BASE_URL|examples/[\w/-]+|/ ["']setup\.py["']|\bsetup\.py\b"""),
    "needs-plugins": re.compile(r"OPS_PLUGINS_REPO|\bPLUGINS_REPO\b"),
    "needs-key": re.compile(
        r"""(?:environ(?:\.get)?[\[(]\s*|getenv\(\s*|process\.env\.)["']?(?:OPENAI|ANTHROPIC)_API_KEY"""
    ),
}
# `examples/` alone is data a script may read; only running an Example's setup needs the stack.
STACK_LINE = re.compile(r"setup\.py|OPS_BASE_URL")


def needs_of(text: str) -> set[str]:
    found = set()
    if any(STACK_LINE.search(line) for line in text.splitlines() if "examples" in line or "OPS_BASE_URL" in line):
        found.add("manual")
    for word in ("needs-plugins", "needs-key"):
        if NEEDS[word].search(text):
            found.add(word)
    return found


def check(registry: str, scripts: dict[str, str]) -> list[str]:
    """`scripts` maps a use case id to the text of all its scripts."""
    status = {m.group(1): set(m.group(2).lower().split()) for line in registry.splitlines() if (m := ROW.match(line))}
    misses = []
    for uc, text in sorted(scripts.items()):
        missing = needs_of(text) - status.get(uc, set())
        misses += [f"{uc} needs a {NEEDS_WHAT[w]} but its registry status lacks `{w}`" for w in sorted(missing)]
    return misses


NEEDS_WHAT = {"manual": "standing stack", "needs-plugins": "plugins checkout", "needs-key": "real provider key"}


def scripts_by_id() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted((ROOT / "docs/usecases").glob("*/scripts/test-uc-*")):
        m = re.match(r"test-(uc-[a-z0-9]+(?:-[a-z0-9]+)*?)-(?:api|sdk|cli|ui)\.", path.name)
        if m:
            out[m.group(1)] = out.get(m.group(1), "") + path.read_text(encoding="utf-8") + "\n"
    return out


def self_test() -> int:
    reg = "| uc-1 | s | t | api | current |\n| uc-2 | s | t | api | current needs-plugins |\n"
    cases = [
        ("plugins undeclared", check(reg, {"uc-1": "x = os.environ.get('OPS_PLUGINS_REPO')"}), 1),
        ("plugins declared", check(reg, {"uc-2": "x = os.environ.get('OPS_PLUGINS_REPO')"}), 0),
        ("key undeclared", check(reg, {"uc-1": "os.environ.get('OPENAI_API_KEY')"}), 1),
        ("key deleted, not read", check(reg, {"uc-1": "env.pop('OPENAI_API_KEY', None)"}), 0),
        ("stack undeclared", check(reg, {"uc-1": "run([py, 'examples/chat/01/setup.py'])"}), 1),
        ("a script with no need", check(reg, {"uc-1": "print('hi')"}), 0),
    ]
    wrong = [name for name, got, n in cases if len(got) != n]
    if wrong:
        print(f"check_usecase_needs self-test failed: {wrong}", file=sys.stderr)
        return 1
    print(f"check_usecase_needs self-test: {len(cases)} cases, each undeclared need is caught")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    misses = check(REGISTRY.read_text(encoding="utf-8"), scripts_by_id())
    for m in misses:
        print(m, file=sys.stderr)
    print(f"check_usecase_needs: {len(misses)} undeclared needs")
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
