#!/usr/bin/env python3
"""One worker of `make uc-impacted`: claims UI use cases from the shared list one at a time and runs each.

    python3 scripts/uc_shard.py <outdir> <uc>...

Every worker gets the whole list and claims an id by creating <outdir>/claims/<id>, slowest of the last run first, so
the workers stay busy until the list is empty, whatever each use case costs. A use case's full output goes to
<outdir>/<id>.log and one line (status, id, seconds) to <outdir>/results.<pid>.tsv, which `uc_impacted.py --summary`
reads. A use case still running UC_TIMEOUT seconds (default 240) after it started is stopped and counted as failed:
a script waiting out its element timeouts on a broken page otherwise holds a worker for ten minutes.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

TIMEOUT = int(os.environ.get("UC_TIMEOUT", "240"))
# Seconds each use case took in the last run on this machine, written by `uc_impacted.py --summary`.
SECONDS_FILE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ops-ai" / "uc-seconds.json"


def longest_first(ids: list[str]) -> list[str]:
    """Slowest first, so the last use case a worker claims is a short one and the workers finish together."""
    try:
        seen = json.loads(SECONDS_FILE.read_text())
    except (OSError, ValueError):
        return ids
    return sorted(ids, key=lambda uc: -seen.get(uc, 0))


def started(log: Path) -> bool:
    """True once the use case runs: until then the log holds only at-most.py's note that it waits for a free slot."""
    try:
        return any(line and not line.startswith(b"at-most:") for line in log.read_bytes().splitlines())
    except OSError:
        return False


def run(uc: str, log: Path) -> bool:
    with log.open("wb") as out:
        proc = subprocess.Popen(
            ["make", "-s", "usecase-test", "LAYER=ui", f"UC={uc}"],
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        # The limit counts from the first output other than the slot note, so waiting for a slot another session holds
        # is not a use case that hung.
        began = None
        while proc.poll() is None:
            began = began or (time.monotonic() if started(log) else None)
            if began is not None and time.monotonic() - began > TIMEOUT:
                break
            time.sleep(1)
        if proc.poll() is not None:
            return proc.returncode == 0
        # SIGTERM first: the harness stops its services on it; a stack left behind holds the next run's ports.
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        out.write(f"\nFAIL stopped after {TIMEOUT}s (UC_TIMEOUT)\n".encode())
        return False


def main() -> int:
    out, ids = Path(sys.argv[1]), sys.argv[2:]
    (out / "claims").mkdir(parents=True, exist_ok=True)
    failed = False
    for uc in longest_first(ids):
        try:
            (out / "claims" / uc).mkdir()
        except FileExistsError:
            continue
        start = time.monotonic()
        ok = run(uc, out / f"{uc}.log")
        failed |= not ok
        with (out / f"results.{os.getpid()}.tsv").open("a") as f:
            f.write(f"{'PASS' if ok else 'FAIL'}\t{uc}\t{round(time.monotonic() - start)}\n")
        if os.environ.get("VERBOSE"):
            print((out / f"{uc}.log").read_text(errors="replace"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
