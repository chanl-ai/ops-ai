"""Run several use cases at once, at most --slots together, and print one line per run.

Each run is `make usecase-test UC=<id> [LAYER=<layer>]`, so the slot guard in scripts/at-most.py and the
per-run isolated databases still apply. A list run one at a time took 40+ minutes; this keeps every slot busy.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = Path(os.environ.get("OPS_EVIDENCE_DIR", ROOT / ".logs" / "usecases")) / "batch"


STARTED_ENV = "OPS_SLOT_STARTED_FILE"


def run(item: str, timeout: int, cmd: list[str] | None = None) -> tuple[str, int, float, float, Path]:
    """Returns (item, code, seconds waited for a slot, seconds run, log).

    The timeout counts from the moment scripts/at-most.py gets a slot and touches the file named by STARTED_ENV, so
    time queued behind other batches never uses it up. A command that never touches the file (no slot guard) is
    timed from its start.
    """
    uc, _, layer = item.partition(":")
    cmd = cmd or ["make", "-s", "usecase-test", f"UC={uc}"] + ([f"LAYER={layer}"] if layer else [])
    log = LOGS / f"{item.replace(':', '-')}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "started"
        env = {**os.environ, STARTED_ENV: str(marker)}
        began = time.monotonic()
        started: float | None = None
        with log.open("w") as out:
            proc = subprocess.Popen(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, env=env)
            code: int | None = None
            while code is None:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    code = proc.wait(timeout=0.1)
                if started is None and marker.exists():
                    started = time.monotonic()
                if code is None and started is not None and time.monotonic() - started > timeout:
                    proc.kill()
                    proc.wait()
                    code = 124
        end = time.monotonic()
    started = began if started is None else started
    return item, code, started - began, end - started, log


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

    def one(item: str) -> tuple[str, int, float, float, Path]:
        return run(item, timeout)

    with ThreadPoolExecutor(max_workers=args.slots) as pool:
        for item, code, waited, ran, log in pool.map(one, items):
            word = "PASS" if code == 0 else ("TIMEOUT" if code == 124 else "FAIL")
            failed += code != 0
            split = f"  (waited {waited:.0f}s, ran {ran:.0f}s)" if code == 124 else ""
            print(f"{word:7} {item:16} {waited + ran:6.0f}s  {log.relative_to(ROOT)}{split}", flush=True)
    print(f"{len(items) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
