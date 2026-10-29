"""`make setup` / `make setup ANSWERS=<file>`: asks what a person has, tests each answer live, and writes settings
only for what passed (docs/deploy/install.md, "Set up with make setup"). Exits with the number of FAIL lines.

    python -m setup [--answers FILE]        with scripts/ and deploy/database/ on PYTHONPATH (make setup sets both)
    SETUP_FILE=<path> python -m setup ...   write somewhere other than the file the RUNS_ON answer picks
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from setup import trust_store
from setup.questions import ROOT, for_install, read_answers, run, target
from setup.settings import write


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--answers", type=Path, help="KEY=VALUE answers; no question is asked")
    a = ap.parse_args()
    trust_store()
    answers = read_answers(a.answers) if a.answers else None
    runs_on, results = run(answers)
    for r in results:
        print(r.line(), flush=True)
    failed = sum(not r.ok for r in results)
    path = target(runs_on)
    if runs_on in ("docker",):
        results = for_install(results)
    written = write(path, results)
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    print(f"\nsettings: {', '.join(written) or 'nothing new'} in {shown} (mode 600)")
    if runs_on == "kubernetes":
        overlay = path.parent
        print(f"then: uv run python deploy/k8s/write_secrets.py --overlay {overlay.relative_to(ROOT)} ... and")
        print(f"      kubectl apply -k {overlay.relative_to(ROOT)} (docs/deploy/kubernetes.md)")
    print(f"{failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(main())
