"""CI's test shards (scripts/test_shard.py), by failure mode: a test file runs in no shard or in two, so a red test is
never run or a shard repeats another's work; the shards are uneven, so the run waits on the longest; a bad shard
number runs nothing and passes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import test_shard  # noqa: E402


def write(tests: Path, name: str, count: int) -> None:
    tests.joinpath(name).write_text("".join(f"def test_{i}() -> None:\n    pass\n\n" for i in range(count)))


def test_every_file_runs_in_exactly_one_shard_for_both_long_suites() -> None:
    for svc, n in (("agents-service", 6), ("tools-service", 5)):
        tests = ROOT / "services" / svc / "tests"
        shards = test_shard.shards(tests, n)
        placed = [f for s in shards for f in s]
        assert sorted(placed) == sorted(tests.rglob("test_*.py")), svc
        assert len(placed) == len(set(placed)), svc


def test_shards_differ_by_no_more_than_the_heaviest_file(tmp_path: Path) -> None:
    for name, count in (("test_a.py", 40), ("test_b.py", 3), ("test_c.py", 25), ("test_d.py", 25), ("test_e.py", 7)):
        write(tmp_path, name, count)
    loads = [sum(test_shard.weigh(f) for f in s) for s in test_shard.shards(tmp_path, 2)]
    assert max(loads) - min(loads) <= 40, loads


def test_a_shard_number_outside_the_count_is_refused() -> None:
    run = subprocess.run(
        [sys.executable, "scripts/test_shard.py", "services/tools-service/tests", "4/3"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 2 and run.stdout == "", run
