"""No compose file nests a required variable (`${B:?}`) inside another's default (`${A:-...}`). Compose 2.38 evaluates
the inner `:?` even when A is set, so `${OPS_DATABASE_URL:-${OPS_DATABASE_URL_PLATFORM:?...}}` refused every builtin
and auto install (which set only OPS_DATABASE_URL) on the release runner, while newer versions accepted it."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NESTED_REQUIRED = re.compile(r"\$\{[A-Za-z0-9_]+:?-[^}\n]*\$\{[A-Za-z0-9_]+:?\?")


def test_no_required_variable_inside_a_default() -> None:
    files = sorted((ROOT / "deploy/compose").glob("*.yaml"))
    assert files, "no compose files found; the scan is looking in the wrong place"
    hits = [
        f"{f.relative_to(ROOT)}:{n}: {line.strip()}"
        for f in files
        for n, line in enumerate(f.read_text().splitlines(), 1)
        if NESTED_REQUIRED.search(line)
    ]
    assert hits == []
