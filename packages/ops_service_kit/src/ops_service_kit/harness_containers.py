"""Docker containers a test or use-case run starts for itself, removed even when the run is killed.

`--rm` and a `finally` cover a run that ends normally. A run stopped by SIGTERM (a timeout, a parent script's kill) or
SIGKILL runs neither, and its containers were left running: 29 of one fake OAuth server and as many OPAs piled up
across builders' runs, about 4 GB of Docker memory. So every container is labelled with the pid of the process that
started it, and each start first removes the labelled containers whose process is gone.
Used by scripts and tests only, never by a running service.
"""

from __future__ import annotations

import os
import subprocess

OWNER = "ops.harness.owner"


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """`docker run -d --rm <args>` owned by this process, after removing the containers of runs that have ended."""
    reap()
    cmd = ["docker", "run", "-d", "--rm", "--label", f"{OWNER}={os.getpid()}", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def owned_by(pid: int) -> list[str]:
    """The ids of the running containers `pid` started."""
    found = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"label={OWNER}={pid}"], capture_output=True, text=True, check=False
    )
    return found.stdout.split()


def reap() -> None:
    """Removes every labelled container whose starting process has exited."""
    listed = subprocess.run(
        ["docker", "ps", "--filter", f"label={OWNER}", "--format", f'{{{{.ID}}}} {{{{.Label "{OWNER}"}}}}'],
        capture_output=True,
        text=True,
        check=False,
    )
    orphans: list[str] = []
    for line in listed.stdout.splitlines():
        cid, _, pid = line.partition(" ")
        if pid.isdigit() and not _alive(int(pid)):
            orphans.append(cid)
    if orphans:
        subprocess.run(["docker", "rm", "-f", *orphans], capture_output=True, check=False)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
