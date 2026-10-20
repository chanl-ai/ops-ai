"""The process host as a container runs it: a real subprocess on a real config, driven by signals.

One test per failure mode: a crashed service stays down, a stop leaves processes behind, the setting starts processes
it does not name, a bad setting or an unset secret starts a half-configured stack, a crash loop never reaches the
machine's supervisor, two services share one process's env, and one service inherits another's secret.
"""

from __future__ import annotations

import http.server
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable
from pathlib import Path

HOST = Path(__file__).parents[1] / "ops_host.py"
PY = sys.executable


def write_config(tmp: Path, body: str) -> Path:
    path = tmp / "processes.toml"
    path.write_text(textwrap.dedent(body))
    return path


def script(tmp: Path, name: str, code: str) -> str:
    path = tmp / f"{name}.py"
    path.write_text(textwrap.dedent(code))
    return str(path)


def start(config: Path, **env: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [PY, str(HOST), str(config)],
        env={"PATH": os.environ["PATH"], **env},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def until(check: Callable[[], bool], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.1)
    return False


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_service_that_crashes_is_started_again(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    crash_once = script(
        tmp_path,
        "crash_once",
        f"""
        import time
        from pathlib import Path
        runs = Path({str(runs)!r})
        n = len(runs.read_text()) if runs.exists() else 0
        runs.write_text("x" * (n + 1))
        if n == 0:
            raise SystemExit(1)
        time.sleep(60)
        """,
    )
    config = write_config(
        tmp_path,
        f"""
        [process.svc]
        command = [{PY!r}, {crash_once!r}]
        """,
    )
    host = start(config)
    try:
        assert until(lambda: runs.exists() and runs.read_text() == "xx"), "the crashed process was not started again"
        assert host.poll() is None
    finally:
        host.send_signal(signal.SIGTERM)
        host.wait(timeout=20)


def test_sigterm_stops_every_process_and_its_children(tmp_path: Path) -> None:
    pids = tmp_path / "pids"
    parent = script(
        tmp_path,
        "parent",
        f"""
        import subprocess, sys, time
        from pathlib import Path
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        Path({str(pids)!r}).write_text(f"{{child.pid}}")
        time.sleep(60)
        """,
    )
    config = write_config(
        tmp_path,
        f"""
        [host]
        grace_seconds = 3
        [process.svc]
        command = [{PY!r}, {parent!r}]
        """,
    )
    host = start(config)
    assert until(lambda: pids.exists() and pids.read_text() != "")
    grandchild = int(pids.read_text())
    host.send_signal(signal.SIGTERM)
    out, _ = host.communicate(timeout=20)
    assert host.returncode == 0, out
    assert until(lambda: not alive(grandchild), 5), "a child of the stopped process is still running"


def test_the_setting_starts_only_the_services_it_names_each_with_its_own_env(tmp_path: Path) -> None:
    record = script(
        tmp_path,
        "record",
        f"""
        import os, sys, time
        from pathlib import Path
        Path({str(tmp_path)!r}, sys.argv[1]).write_text(os.environ["OPS_SERVICE_SIGNING_KID"])
        time.sleep(60)
        """,
    )
    config = write_config(
        tmp_path,
        f"""
        [process.agents]
        command = [{PY!r}, {record!r}, "agents.out"]
        env = {{ OPS_SERVICE_SIGNING_KID = "svc-agents-1" }}
        [process.tools]
        command = [{PY!r}, {record!r}, "tools.out"]
        env = {{ OPS_SERVICE_SIGNING_KID = "svc-tools-1" }}
        [process.kb]
        command = [{PY!r}, {record!r}, "kb.out"]
        env = {{ OPS_SERVICE_SIGNING_KID = "svc-kb-1" }}
        """,
    )
    host = start(config, OPS_ENABLED_SERVICES="tools,agents")
    try:
        assert until(lambda: (tmp_path / "agents.out").exists() and (tmp_path / "tools.out").exists())
        time.sleep(0.5)
        assert not (tmp_path / "kb.out").exists(), "kb started though the setting does not name it"
        assert (tmp_path / "agents.out").read_text() == "svc-agents-1"
        assert (tmp_path / "tools.out").read_text() == "svc-tools-1"
    finally:
        host.send_signal(signal.SIGTERM)
        host.wait(timeout=20)


def test_a_withheld_secret_reaches_only_the_process_that_names_it(tmp_path: Path) -> None:
    record = script(
        tmp_path,
        "record",
        f"""
        import os, sys, time
        from pathlib import Path
        seen = [k for k in ("OPS_DATABASE_URL", "OPS_DATABASE_URL_TOOLS", "OPS_SVC_KEY_TOOLS") if k in os.environ]
        Path({str(tmp_path)!r}, sys.argv[1]).write_text(os.environ.get("OPS_DATABASE_URL", "-") + "|" + ",".join(seen))
        time.sleep(60)
        """,
    )
    config = write_config(
        tmp_path,
        f"""
        [host]
        withhold = ["OPS_DATABASE_URL", "OPS_DATABASE_URL_*", "OPS_SVC_KEY_*"]
        [process.tools]
        command = [{PY!r}, {record!r}, "tools.out"]
        env = {{ OPS_DATABASE_URL = "${{OPS_DATABASE_URL_TOOLS}}" }}
        [process.console]
        command = [{PY!r}, {record!r}, "console.out"]
        """,
    )
    host = start(
        config,
        OPS_DATABASE_URL="superuser",
        OPS_DATABASE_URL_TOOLS="tools-login",
        OPS_SVC_KEY_TOOLS="k",
    )
    try:
        assert until(lambda: (tmp_path / "tools.out").exists() and (tmp_path / "console.out").exists())
        time.sleep(0.3)
        assert (tmp_path / "tools.out").read_text() == "tools-login|OPS_DATABASE_URL"
        assert (tmp_path / "console.out").read_text() == "-|", "console inherited a withheld secret"
    finally:
        host.send_signal(signal.SIGTERM)
        host.wait(timeout=20)


def test_an_unknown_name_or_an_unset_secret_starts_nothing(tmp_path: Path) -> None:
    marker = tmp_path / "started"
    touch = script(tmp_path, "touch", f"from pathlib import Path; Path({str(marker)!r}).write_text('x')")
    config = write_config(
        tmp_path,
        f"""
        [process.agents]
        command = [{PY!r}, {touch!r}]
        env = {{ OPS_SERVICE_SIGNING_KEY = "${{OPS_SVC_KEY_AGENTS}}" }}
        """,
    )
    unknown = start(config, OPS_ENABLED_SERVICES="agents,billing", OPS_SVC_KEY_AGENTS="k")
    out, _ = unknown.communicate(timeout=10)
    assert unknown.returncode == 2 and "names billing" in out, out
    unset = start(config)
    out, _ = unset.communicate(timeout=10)
    assert unset.returncode == 2 and "unset in the environment: OPS_SVC_KEY_AGENTS" in out, out
    assert not marker.exists()


def test_a_crash_loop_stops_the_host_with_a_failure(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        f"""
        [host]
        max_restarts = 2
        backoff_max_seconds = 0.2
        [process.broken]
        command = [{PY!r}, "-c", "raise SystemExit(3)"]
        """,
    )
    host = start(config)
    out, _ = host.communicate(timeout=30)
    assert host.returncode == 1, out
    assert "broken: exited 3 times" in out, out


def test_a_command_that_cannot_start_stops_the_host_and_leaves_nothing_running(tmp_path: Path) -> None:
    pids = tmp_path / "pids"
    long = script(
        tmp_path,
        "long",
        f"""
        import os, time
        from pathlib import Path
        Path({str(pids)!r}).write_text(str(os.getpid()))
        time.sleep(60)
        """,
    )
    config = write_config(
        tmp_path,
        f"""
        [host]
        max_restarts = 1
        backoff_max_seconds = 0.2
        [process.long]
        command = [{PY!r}, {long!r}]
        [process.missing]
        command = ["{tmp_path}/no-such-binary"]
        """,
    )
    host = start(config)
    out, _ = host.communicate(timeout=30)
    assert host.returncode == 1, out
    assert "missing: could not start" in out, out
    assert pids.exists() and not alive(int(pids.read_text())), "a process outlived the host"


def test_check_reports_a_down_process_and_fails(tmp_path: Path) -> None:
    server = http.server.HTTPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    up = f"http://127.0.0.1:{server.server_port}/"
    config = write_config(
        tmp_path,
        f"""
        [process.up]
        command = ["true"]
        check = "{up}"
        [process.gone]
        command = ["true"]
        ready = "http://127.0.0.1:9/health"
        [process.worker]
        command = ["no-such-worker-command"]
        """,
    )
    try:
        run = subprocess.run(
            [PY, str(HOST), "--check", str(config)], capture_output=True, text=True, timeout=30, check=False
        )
    finally:
        server.shutdown()
    lines = run.stdout.splitlines()
    assert run.returncode == 1, run.stdout
    assert lines[0].startswith("ok   up: 200")
    assert lines[1].startswith("DOWN gone: unreachable")
    assert lines[2] == "DOWN worker: not running"
