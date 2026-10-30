"""scripts/stack.sh under `set -euo pipefail`, by failure mode: a reader that stops early (`| head -1`, `grep -q`)
leaves the writer to die of SIGPIPE, the pipeline answers 141, and `set -e` ends the script. `start worker` stopped
this way whenever two old workers were alive, leaving the worker down while the old ones ran old code.

Each test runs the script's own lines against stand-ins for pgrep, ps and lsof, whose second line comes after the
reader has stopped, so the early stop happens every time rather than when the scheduler allows."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STACK = (ROOT / "scripts/stack.sh").read_text()
NEEDLE = "OPS_FILES_URL=http://127.0.0.1:8735"

STANDINS = f"""
FILES_PORT=8735
pgrep() {{ echo 111; echo 222; }}
ps() {{ local pid=${{@: -1}}; [[ $pid == 222 ]] && sleep 0.3; echo "python -m ops_agents.api.worker {NEEDLE}"; \
  sleep 0.3; for i in $(seq 1 2000); do echo "VAR_$i=x"; done; }}
lsof() {{ echo 4242; sleep 0.3; echo 4243; }}
"""


def function(name: str) -> str:
    """The function as the script defines it, on one line or many."""
    m = re.search(rf"^{name}\(\) \{{ .*\}}$\n", STACK, flags=re.M) or re.search(
        rf"^{name}\(\) \{{\n.*?^\}}\n", STACK, flags=re.M | re.S
    )
    assert m, f"stack.sh has no {name}()"
    return m.group(0)


def run(body: str) -> subprocess.CompletedProcess[str]:
    script = "set -euo pipefail\n" + STANDINS + "".join(function(f) for f in FUNCTIONS) + body
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, check=False)


FUNCTIONS = [
    f
    for f in ("pid_env", "stack_cmd_pids", "stack_worker_leftover", "listener")
    if re.search(rf"^{f}\(\)", STACK, flags=re.M)
]


def test_a_live_old_worker_does_not_stop_the_worker_start() -> None:
    # The line `start worker` runs to find a worker whose pidfile was lost, as it stands in the script.
    line = next(line.strip() for line in STACK.splitlines() if line.strip().startswith("leftover=$("))
    done = run(f'{line}\necho "leftover=$leftover"\n')
    assert done.returncode == 0 and "leftover=111" in done.stdout, (done.returncode, done.stdout, done.stderr)


def test_a_port_with_two_listeners_does_not_stop_the_script() -> None:
    done = run('pid=$(listener 8710)\necho "pid=$pid"\n')
    assert done.returncode == 0 and "pid=4242" in done.stdout, (done.returncode, done.stdout, done.stderr)
