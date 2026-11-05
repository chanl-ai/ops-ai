"""Prints the test files of one shard of a suite, for CI to run a long suite across several runners at once.

Usage: python scripts/test_shard.py <tests dir> <i>/<n>
Each test file goes to exactly one shard. Files are weighed by how many tests they define, since a test costs about
the same everywhere (its app and database setup dominate), and placed heaviest first on the lightest shard, so the
shards end close together. The split depends only on the files, so every runner computes the same one.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TEST = re.compile(r"^\s*(?:async\s+)?def\s+test_", re.MULTILINE)


def weigh(path: Path) -> int:
    return max(1, len(TEST.findall(path.read_text(encoding="utf-8"))))


def shards(tests: Path, n: int) -> list[list[Path]]:
    files = sorted(tests.rglob("test_*.py"))
    out: list[list[Path]] = [[] for _ in range(n)]
    load = [0] * n
    for f in sorted(files, key=lambda p: (-weigh(p), str(p))):
        i = load.index(min(load))
        out[i].append(f)
        load[i] += weigh(f)
    return [sorted(s) for s in out]


def main(argv: list[str]) -> int:
    if len(argv) != 3 or not re.fullmatch(r"\d+/\d+", argv[2]):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    tests = Path(argv[1])
    i, n = (int(x) for x in argv[2].split("/"))
    if not 1 <= i <= n:
        print(f"test_shard: shard {i} is not between 1 and {n}", file=sys.stderr)
        return 2
    base = tests.parent
    print(" ".join(str(p.relative_to(base)) for p in shards(tests, n)[i - 1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
