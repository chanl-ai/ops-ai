"""The runner's walls, each driven through a real guest: no network, no host files, no environment, and memory, time
and call limits that hold per run even while runs overlap."""

from __future__ import annotations

import threading
from typing import Any

from ops_runner.domain import Limits, RunResult
from ops_runner.wasm import WasmPython


def refuse(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"ok": False, "error": {"code": "binding_forbidden", "message": tool}}


def run(rt: WasmPython, body: str, limits: Limits | None = None, answer: Any = refuse, input: Any = None) -> RunResult:
    source = "def main(input):\n" + "\n".join(f"    {line}" for line in body.splitlines())
    return rt.run(source, "main", input, limits or Limits(time_s=5), answer)


def test_the_output_and_log_come_back(runtime: WasmPython) -> None:
    r = run(runtime, "print('seen', input['n'])\nreturn {'double': input['n'] * 2}", input={"n": 21})
    assert r.ok and r.output == {"double": 42}
    assert "seen 21" in r.log


def test_a_socket_cannot_be_opened(runtime: WasmPython) -> None:
    r = run(runtime, "import socket\nsocket.socket().connect(('1.1.1.1', 443))\nreturn 1")
    assert not r.ok and r.error is not None and r.error["code"] == "function_error"
    assert "OSError" in r.error["message"]


def test_the_host_is_out_of_reach(runtime: WasmPython) -> None:
    body = "import os\ntry:\n    open('/etc/passwd').read()\n    host = True\nexcept OSError:\n    host = False\n"
    r = run(runtime, body + "return {'env': dict(os.environ), 'host': host, 'app': os.listdir('/app')}")
    assert r.ok and r.output == {"env": {}, "host": False, "app": ["main.py"]}


def test_memory_past_the_cap_stops_the_run(runtime: WasmPython) -> None:
    r = run(runtime, "x = bytearray(300 << 20)\nreturn len(x)", Limits(memory_mb=128, time_s=5))
    assert not r.ok and r.error == {"code": "memory_limit", "message": "The function used more memory than its limit."}


def test_a_loop_past_its_time_limit_is_stopped(runtime: WasmPython) -> None:
    r = run(runtime, "while True:\n    pass", Limits(time_s=0.5))
    assert not r.ok and r.error is not None and r.error["code"] == "time_limit"
    assert r.execute_ms < 3000


def test_overlapping_runs_keep_their_own_time_limits(runtime: WasmPython) -> None:
    """A short limit stopping one run must not stop another that started with a longer one."""
    results: dict[str, RunResult] = {}

    def go(name: str, body: str, limits: Limits) -> None:
        results[name] = run(runtime, body, limits)

    slow = "s = 0\nfor k in range(6_000_000):\n    s += k\nreturn s"
    threads = [
        threading.Thread(target=go, args=("loop", "while True:\n    pass", Limits(time_s=0.3))),
        threading.Thread(target=go, args=("slow", slow, Limits(time_s=20))),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results["loop"].error is not None and results["loop"].error["code"] == "time_limit"
    assert results["slow"].ok, results["slow"].error
    assert results["slow"].execute_ms > 300


def test_calls_past_the_limit_are_refused(runtime: WasmPython) -> None:
    def fine(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "output": {"n": 1}}

    r = run(runtime, "for _ in range(5):\n    ops.call('get_account')\nreturn 1", Limits(time_s=5, calls=3), fine)
    assert not r.ok and r.error is not None and r.error["code"] == "call_limit"
    assert [t["ok"] for t in r.trace] == [True, True, True, False]


def test_a_refused_call_raises_in_the_function_with_its_code(runtime: WasmPython) -> None:
    r = run(runtime, "return ops.call('delete_everything', {})")
    assert not r.ok and r.error == {"code": "binding_forbidden", "message": "delete_everything"}


def test_a_secret_leaves_the_sandbox_as_a_handle(runtime: WasmPython) -> None:
    seen: list[dict[str, Any]] = []

    def record(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        seen.append(args)
        return {"ok": True, "output": {"balance": 10}}

    r = run(runtime, "k = ops.secret('BANK_KEY')\nops.call('get_account', {'key': k})\nreturn repr(k)", answer=record)
    assert r.ok and r.output == "<secret BANK_KEY>"
    assert seen == [{"key": {"$secret": "BANK_KEY"}}]
