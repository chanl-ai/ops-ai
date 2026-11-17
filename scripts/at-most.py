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
import signal
import subprocess
import sys
import time

DIR = os.environ.get("OPS_SLOT_DIR", "/tmp/ops-ai-slots")
GRACE = 3.0


def kill_group(pgid: int) -> None:
    """TERM the command's whole process group, KILL what is left after the grace period.

    macOS answers EPERM, not ESRCH, for a group whose only members have exited and wait to be reaped, so a refusal
    means the same as a missing group: nothing is left to stop.
    """
    gone = (ProcessLookupError, PermissionError)
    for sig, wait in ((signal.SIGTERM, GRACE), (signal.SIGKILL, 1.0)):
        try:
            os.killpg(pgid, sig)
        except gone:
            return
        end = time.time() + wait
        while time.time() < end:
            try:
                os.killpg(pgid, 0)
            except gone:
                return
            time.sleep(0.05)


def run_in_group(cmd: list[str]) -> int:
    """Runs cmd in its own session so a signal, a dead parent or our own exit can take the whole tree down.

    A plain subprocess.call leaves the child running when this wrapper is killed (macOS has no PDEATHSIG), and the
    orphan then outlives the run that wanted it, a headless browser included.
    """
    parent = os.getppid()
    stop: list[int] = []
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda signum, _frame: stop.append(signum))
    proc = subprocess.Popen(cmd, start_new_session=True)
    try:
        while True:
            try:
                return proc.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                if stop:
                    return 128 + stop[0]
                if os.getppid() != parent or parent == 1:  # already orphaned before we looked
                    return 129
    finally:
        kill_group(proc.pid)
        proc.poll()


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
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode())  # the kernel frees the lock when this process dies
            started = os.environ.get("OPS_SLOT_STARTED_FILE")  # scripts/usecase_batch.py starts its timeout from this
            if started:
                open(started, "w").close()
            return run_in_group(cmd)
        if not said:
            print(f"at-most: {n} {kind} runs already going; waiting for one to finish", file=sys.stderr, flush=True)
            said = True
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
