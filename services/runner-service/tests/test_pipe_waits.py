"""The host's two waits for a guest that has not opened its end of a pipe yet: each waits on the guest's thread, so it
stops waiting the moment the guest opens the pipe or ends. A stand-in guest opens the pipe from inside the wait, so
nothing here sleeps or depends on timing."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ops_runner.domain import Limits, RunResult
from ops_runner.wasm import Run, WasmPython, open_writer
from ops_service_kit.settings import RunnerWaits

WAITS = RunnerWaits()


class Guest(threading.Thread):
    """A guest thread that is alive until told otherwise and does `on_wait` the first time the host waits on it. A
    host that polls without waiting on it sees it end after a hundred looks, so that failure ends rather than hangs."""

    def __init__(self, on_wait: Callable[[], None], *, alive: bool = True) -> None:
        super().__init__()
        self.on_wait = on_wait
        self.alive = alive
        self.looks = 0
        self.waits: list[float | None] = []

    def is_alive(self) -> bool:
        self.looks += 1
        return self.alive and self.looks < 100

    def join(self, timeout: float | None = None) -> None:
        self.waits.append(timeout)
        if len(self.waits) == 1:
            self.on_wait()


def no_calls(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    raise AssertionError("no call expected")


def test_the_host_writes_once_the_guest_opens_its_stdin(tmp_path: Path) -> None:
    fifo = str(tmp_path / "in")
    os.mkfifo(fifo)
    readers: list[int] = []
    guest = Guest(lambda: readers.append(os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)))
    fd = open_writer(fifo, guest, WAITS.open_poll_s)
    assert fd is not None and guest.waits == [WAITS.open_poll_s]
    os.close(fd)
    os.close(readers[0])


def test_the_host_stops_waiting_for_stdin_when_the_guest_has_ended(tmp_path: Path) -> None:
    fifo = str(tmp_path / "in")
    os.mkfifo(fifo)
    guest = Guest(lambda: None, alive=False)
    assert open_writer(fifo, guest, WAITS.open_poll_s) is None and guest.waits == []


def test_the_host_stops_reading_when_the_guest_has_closed_its_stdout_and_ends(tmp_path: Path) -> None:
    run = Run(cast_runtime(), tmp_path, time.monotonic(), Limits(), no_calls)
    os.mkfifo(run.stdout)
    out_fd = os.open(run.stdout, os.O_RDONLY | os.O_NONBLOCK)
    os.close(os.open(run.stdout, os.O_WRONLY | os.O_NONBLOCK))  # the guest's end, opened and closed with nothing said
    guest = Guest(lambda: setattr(guest, "alive", False))
    result = RunResult(ok=False)
    started = time.monotonic()
    run.converse(result, guest, out_fd, None, started + 5)
    assert guest.waits == [WAITS.read_poll_s] and not result.ok and time.monotonic() - started < 1
    os.close(out_fd)


def cast_runtime() -> WasmPython:
    """`converse` never touches the runtime; a run built only to read its pipes needs none."""
    runtime = object.__new__(WasmPython)
    runtime.waits = WAITS
    return runtime
