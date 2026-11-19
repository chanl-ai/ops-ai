"""usecase_batch: the timeout counts from when the run gets a slot, not from when it was queued."""

import importlib.util
import sys
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("usecase_batch", Path(__file__).resolve().parents[1] / "usecase_batch.py")
batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch)

# Stands in for `make usecase-test` behind at-most.py: waits for a slot, then touches the started file and finishes.
SLOT_THEN_FINISH = (
    "import os, time\ntime.sleep({wait})\nopen(os.environ['OPS_SLOT_STARTED_FILE'], 'w').close()\ntime.sleep({run})\n"
)


def go(wait: float, run: float, timeout: int):
    cmd = [sys.executable, "-c", SLOT_THEN_FINISH.format(wait=wait, run=run)]
    return batch.run("uc-test", timeout, cmd)


def test_wait_for_a_slot_longer_than_the_timeout_still_passes():
    _, code, waited, ran, _ = go(wait=1.5, run=0.1, timeout=1)
    assert code == 0
    assert waited >= 1.5 and ran < 1


def test_a_run_that_overruns_after_getting_its_slot_times_out_with_the_split():
    _, code, waited, ran, _ = go(wait=0.3, run=5, timeout=1)
    assert code == 124
    assert 0.3 <= waited < 1 and 1 <= ran < 3
