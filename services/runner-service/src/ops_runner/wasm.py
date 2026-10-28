"""Python on WASM: CPython 3.12 compiled to WASI, run by wasmtime with a memory cap, a time limit and no network.

The guest's only channel out is its stdin and stdout, two fifos in the run's own directory. The prelude reads one
request line (source, entry, input); `ops.call` writes a call line and blocks reading the answer; the run ends with one
result or error line. CPython in WASI cannot call host functions without ctypes, so the pipes are the bridge. WASI
preview 1 has no sockets, the guest's environment is empty, and its only directory is the run's, deleted after it."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import select
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from wasmtime import Config, Engine, ExitTrap, Linker, Module, Store, Trap, WasiConfig

from .domain import CallAnswer, Limits, RunResult, failure

# Seconds between epoch ticks. A run's time limit is counted in ticks on its own store, so overlapping runs on the one
# engine each keep their own limit; a per-run timer advancing the shared epoch would stop every run in flight.
TICK_S = 0.1
# Grace after the limit before the host stops waiting for a guest that trapped but has not let go of its pipes.
GRACE_S = 2.0
LOG_CAP = 8192
OUTPUT_CAP = 1 << 20

# What the guest runs first: reads the request, gives the function `ops`, and writes one result line (guest.py).
PRELUDE = (Path(__file__).parent / "guest.py").read_text()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class WasmPython:
    """One engine and one compiled module for the process; each run gets its own store, directory and pipes."""

    def __init__(self, wasm: Path, *, sha256: str, compiled_dir: Path) -> None:
        if not wasm.is_file():
            raise SystemExit(f"The runner's Python build is missing at {wasm}: run `make runner-wasm`.")
        if (found := sha256_of(wasm)) != sha256:
            raise SystemExit(f"The runner's Python build at {wasm} has SHA-256 {found}, not the pinned {sha256}.")
        cfg = Config()
        cfg.epoch_interruption = True
        # wasmtime's compiled-module cache, in a directory the service owns: a systemd unit has no writable home.
        compiled_dir.mkdir(parents=True, exist_ok=True)
        toml = compiled_dir / "wasmtime-cache.toml"
        toml.write_text(f'[cache]\ndirectory = "{compiled_dir}"\n')
        cfg.cache = str(toml)
        self.engine = Engine(cfg)
        self.module: Module = Module.from_file(self.engine, str(wasm))  # pyright: ignore[reportUnknownMemberType]
        self._stop = threading.Event()
        threading.Thread(target=self._tick, daemon=True, name="wasm-epoch").start()

    def _tick(self) -> None:
        while not self._stop.wait(TICK_S):
            self.engine.increment_epoch()

    def close(self) -> None:
        self._stop.set()

    def run(self, source: str, entry: str, input: Any, limits: Limits, answer: CallAnswer) -> RunResult:
        """Runs `entry(input)` from `source`. Each `ops.call` is handed to `answer` on this thread, which blocks the
        guest until it returns; the call limit is counted here, so the guest cannot raise it."""
        started = time.monotonic()
        work = Path(tempfile.mkdtemp(prefix="ops-run-"))
        try:
            return _Run(self, work, started, limits, answer).execute(source, entry, input)
        finally:
            shutil.rmtree(work, ignore_errors=True)


class _Run:
    def __init__(self, runtime: WasmPython, work: Path, started: float, limits: Limits, answer: CallAnswer) -> None:
        self.runtime = runtime
        self.work = work
        self.started = started
        self.limits = limits
        self.answer = answer
        self.app = work / "app"
        self.stdin, self.stdout, self.stderr = (str(work / n) for n in ("in", "out", "err"))
        self.ended: dict[str, Any] = {}

    def _guest(self) -> None:
        store = Store(self.runtime.engine)
        try:
            store.set_limits(memory_size=self.limits.memory_mb << 20)
            store.set_epoch_deadline(max(1, round(self.limits.time_s / TICK_S)))
            wasi = WasiConfig()
            wasi.argv = ["python", "-I", "-S", "/app/main.py"]
            wasi.preopen_dir(str(self.app), "/app")
            wasi.stdin_file = self.stdin
            wasi.stdout_file = self.stdout
            wasi.stderr_file = self.stderr
            store.set_wasi(wasi)
            linker = Linker(self.runtime.engine)
            linker.define_wasi()
            instance = linker.instantiate(store, self.runtime.module)
            start: Callable[..., Any] = instance.exports(store)["_start"]  # pyright: ignore[reportAssignmentType]
            start(store)
        except ExitTrap as e:
            self.ended["exit"] = e.code
        except Trap as e:
            self.ended["trap"] = str(e)
        except Exception as e:  # a wasmtime error before the guest starts
            self.ended["setup"] = f"{type(e).__name__}: {e}"
        finally:
            # Dropping the store closes the guest's ends of the pipes, so the host's reads see end of file.
            del store

    def execute(self, source: str, entry: str, input: Any) -> RunResult:
        self.app.mkdir()
        (self.app / "main.py").write_text(PRELUDE)
        os.mkfifo(self.stdin)
        os.mkfifo(self.stdout)
        thread = threading.Thread(target=self._guest, daemon=True, name="wasm-guest")
        thread.start()
        # A fifo's open blocks until the other end opens. Non-blocking opens keep a guest that dies during set-up from
        # hanging the host.
        out_fd = os.open(self.stdout, os.O_RDONLY | os.O_NONBLOCK)
        in_fd = _open_writer(self.stdin, thread)
        result = RunResult(ok=False, create_ms=self._ms())
        deadline = self.started + self.limits.time_s + GRACE_S
        try:
            if in_fd is not None:
                _write(in_fd, {"source": source, "entry": entry, "input": input})
            self._converse(result, thread, out_fd, in_fd, deadline)
        finally:
            if in_fd is not None:
                os.close(in_fd)
            thread.join(timeout=GRACE_S)
            os.close(out_fd)
        if not result.ok and result.error is None:
            result.error = self._why(thread)
        result.log = _tail(self.stderr)
        result.execute_ms = self._ms() - result.create_ms
        return result

    def _converse(
        self, result: RunResult, thread: threading.Thread, out_fd: int, in_fd: int | None, deadline: float
    ) -> None:
        buf = bytearray()
        while (left := deadline - time.monotonic()) > 0:
            readable, _, _ = select.select([out_fd], [], [], min(left, 0.2))
            if not readable:
                if not thread.is_alive():
                    return
                continue
            chunk: bytes = os.read(out_fd, 65536)
            if not chunk:
                if not thread.is_alive():
                    return
                time.sleep(0.01)  # no writer yet: the guest has not opened stdout
                continue
            buf.extend(chunk)
            if len(buf) > OUTPUT_CAP:
                result.error = failure("output_too_large", "The function wrote more than 1 MB at once.")
                return
            while (end := buf.find(b"\n")) >= 0:
                line = bytes(buf[:end])
                del buf[: end + 1]
                try:
                    parsed: Any = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(parsed, dict):
                    continue
                msg = cast(dict[str, Any], parsed)
                if "call" in msg:
                    reply = self._call(result, str(msg["call"]), msg.get("args"))
                    if in_fd is not None:
                        _write(in_fd, reply)
                elif "result" in msg:
                    result.ok, result.output = True, msg["result"]
                    return
                elif "error" in msg:
                    error = cast(dict[str, Any], msg["error"] if isinstance(msg["error"], dict) else {})
                    result.error = failure(str(error.get("code")), str(error.get("message")))
                    return

    def _call(self, result: RunResult, tool: str, args: Any) -> dict[str, Any]:
        result.calls += 1
        if result.calls > self.limits.calls:
            reply: dict[str, Any] = {
                "ok": False,
                "error": failure("call_limit", f"At most {self.limits.calls} calls per run."),
            }
        elif not isinstance(args, dict):
            reply = {"ok": False, "error": failure("invalid_input", "A call's arguments are an object.")}
        else:
            reply = self.answer(tool, cast(dict[str, Any], args))
        error = cast(dict[str, Any], reply.get("error") or {})
        result.trace.append({"tool": tool, "ok": bool(reply.get("ok")), "code": error.get("code")})
        return reply

    def _why(self, thread: threading.Thread) -> dict[str, str]:
        trap = str(self.ended.get("trap", ""))
        if "interrupt" in trap or thread.is_alive() or time.monotonic() >= self.started + self.limits.time_s:
            return failure("time_limit", f"The function ran past its {self.limits.time_s:g} s limit.")
        why = trap or self.ended.get("setup") or f"exit {self.ended.get('exit')}"
        return failure("runner_error", str(why).splitlines()[0][:300])

    def _ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)


def _open_writer(path: str, thread: threading.Thread) -> int | None:
    while True:
        try:
            return os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:  # ENXIO: the guest has not opened its stdin yet
            if not thread.is_alive():
                return None
            time.sleep(0.005)


def _write(fd: int, msg: dict[str, Any]) -> None:
    os.set_blocking(fd, True)
    # A broken pipe means the guest ended; its outcome is read from the trap.
    with contextlib.suppress(BrokenPipeError):
        os.write(fd, (json.dumps(msg) + "\n").encode())


def _tail(path: str) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - LOG_CAP))
            return f.read().decode(errors="replace")
    except OSError:
        return ""
