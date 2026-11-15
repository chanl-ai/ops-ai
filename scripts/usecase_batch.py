"""Run several use cases at once, at most --slots together, and print one line per run.

Each run is `make usecase-test UC=<id> [LAYER=<layer>]`, so the slot guard in scripts/at-most.py and the
per-run isolated databases still apply. A list run one at a time took 40+ minutes; this keeps every slot busy.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / ".logs" / "usecases" / "batch"


def run(item: str, timeout: int) -> tuple[str, int, float, Path]:
    uc, _, layer = item.partition(":")
    cmd = ["make", "-s", "usecase-test", f"UC={uc}"] + ([f"LAYER={layer}"] if layer else [])
    log = LOGS / f"{item.replace(':', '-')}.log"
    started = time.monotonic()
    with log.open("w") as out:
        try:
            done = subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, timeout=timeout, check=False)
            code = done.returncode
        except subprocess.TimeoutExpired:
            code = 124
    return item, code, time.monotonic() - started, log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slots", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=600, help="seconds per use case")
    ap.add_argument("items", nargs="+", help="uc-NNN or uc-NNN:layer")
    args = ap.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)
    items: list[str] = args.items
    timeout: int = args.timeout
    failed = 0

    def one(item: str) -> tuple[str, int, float, Path]:
        return run(item, timeout)

    with ThreadPoolExecutor(max_workers=args.slots) as pool:
        for item, code, secs, log in pool.map(one, items):
            word = "PASS" if code == 0 else ("TIMEOUT" if code == 124 else "FAIL")
            failed += code != 0
            print(f"{word:7} {item:16} {secs:6.0f}s  {log.relative_to(ROOT)}", flush=True)
    print(f"{len(items) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
