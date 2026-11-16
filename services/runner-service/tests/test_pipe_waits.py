"""The host's wait for a guest that has closed its stdout but still runs: a join on the guest's thread, so the run ends
the moment the guest does, however long the configured wait. A runtime with a five-second read wait shows it."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest

from ops_runner.domain import Limits
from ops_runner.fetch import compiled_dir, wasm_path
from ops_runner.wasm import WasmPython
from ops_service_kit.settings import RunnerWaits, Settings


@pytest.fixture(scope="module")
def slow_reads() -> Iterator[WasmPython]:
    settings = Settings()
    rt = WasmPython(
        wasm_path(settings),
        sha256=settings.runner_wasm_sha256,
        compiled_dir=compiled_dir(settings),
        waits=RunnerWaits(read_poll_s=5.0),
    )
    yield rt
    rt.close()


def no_calls(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    raise AssertionError("no call expected")


def test_a_guest_that_closes_its_stdout_ends_the_run_when_it_ends(slow_reads: WasmPython) -> None:
    source = (
        "import os, time\n"
        "def main(i):\n"
        "    os.close(1)\n"
        "    end = time.monotonic() + 0.3\n"
        "    while time.monotonic() < end:\n"
        "        pass\n"
        "    return 1\n"
    )
    started = time.monotonic()
    result = slow_reads.run(source, "main", None, Limits(time_s=10), no_calls)
    assert not result.ok and time.monotonic() - started < 2
