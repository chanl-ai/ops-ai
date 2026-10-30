#!/usr/bin/env python3
"""Runs a command only when fewer than N others of its kind are running on this Mac, waiting for a free slot.

Several builders start browser use-case stacks (a console, eight services, Postgres databases) at once; on 10-30 the
load reached 35 with ten consoles and nine pytest runs, and every run slowed past its timeouts. A slot is an fcntl
lock on /tmp/ops-ai-slots/<kind>-<i>.lock, held for the command's life and freed by the kernel if it dies.
  python3 scripts/at-most.py <N> <kind> -- <command>...
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import time

DIR = "/tmp/ops-ai-slots"


def main() -> int:
    if len(sys.argv) < 5 or sys.argv[3] != "--":
        print("usage: at-most.py <N> <kind> -- <command>...", file=sys.stderr)
        return 2
    n, kind, cmd = int(sys.argv[1]), sys.argv[2], sys.argv[4:]
    os.makedirs(DIR, exist_ok=True)
    said = False
    while True:
        for i in range(n):
            fd = os.open(f"{DIR}/{kind}-{i}.lock", os.O_CREAT | os.O_RDWR, 0o666)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                continue
            return subprocess.call(cmd)
        if not said:
            print(f"at-most: {n} {kind} runs already going; waiting for one to finish", file=sys.stderr, flush=True)
            said = True
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
