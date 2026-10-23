#!/usr/bin/env python3
"""The process host: starts the processes a config file lists, in order, keeps them running, and stops them together.

`python3 ops_host.py <config.toml>` runs in the foreground as a container's main process. Which processes start comes
from OPS_ENABLED_SERVICES (comma-separated names, or `all`), so one image runs every service on one machine or one
service per machine with no change but that setting (decision: services independent of processes).

Each process has its command, its own env (values may name `${VAR}` from the host's environment; a name that is unset
stops the host before anything starts). `[host] withhold` lists names (shell patterns) no process inherits from the
host's environment: one machine holds every service's database login and keys, and each process receives only those
its own env names and an optional `ready` URL the host waits on before starting the next one.
A process that exits is started again after a backoff; one that exits more than `max_restarts` times inside
`restart_window_seconds` stops the host with exit 1, so the machine's supervisor restarts the machine. SIGTERM or
SIGINT stops every process group in reverse order, waits `grace_seconds`, then kills what is left.

`python3 ops_host.py --check <config.toml>` reports each enabled process from outside the host (`fly ssh console`): its
`check` URL, else its `ready` URL, must answer below 400; a process with neither must have its command running. It
prints one line per process and exits 1 when any is down.

Standard library only: it runs before, and apart from, the Python environment the services use.
"""

from __future__ import annotations

import contextlib
import fnmatch
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

_VAR = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


class ConfigError(Exception):
    """The config or the environment cannot start the host; nothing was started."""


@dataclass
class Spec:
    name: str
    command: list[str]
    env: dict[str, str]
    ready: str | None = None
    # A health URL that is not a start gate (agents-service answers 503 until a model is bound); --check reads it.
    check: str | None = None
    ready_timeout: float = 120.0
    cwd: str | None = None


@dataclass
class HostConfig:
    processes: list[Spec]
    grace_seconds: float = 20.0
    max_restarts: int = 5
    restart_window_seconds: float = 300.0
    backoff_max_seconds: float = 30.0
    withhold: list[str] = field(default_factory=list[str])


@dataclass
class Running:
    spec: Spec
    proc: subprocess.Popen[bytes] | None = None
    exits: list[float] = field(default_factory=list[float])
    restart_at: float = 0.0
    # Why the last start failed before a process existed (a missing binary); counted as an exit.
    start_error: str | None = None

    def exited(self) -> bool:
        return self.start_error is not None or (self.proc is not None and self.proc.poll() is not None)

    def how(self) -> str:
        return self.start_error or f"exited with {self.proc.returncode if self.proc else '?'}"


def _expand(text: str, environ: dict[str, str], missing: set[str]) -> str:
    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in environ:
            missing.add(name)
            return ""
        return environ[name]

    return _VAR.sub(sub, text)


def load(path: Path, environ: dict[str, str]) -> HostConfig:
    """The enabled processes with their env expanded; raises ConfigError naming every problem it finds."""
    raw: dict[str, Any] = tomllib.loads(path.read_text())
    host: dict[str, Any] = raw.get("host", {})
    declared: dict[str, dict[str, Any]] = raw.get("process", {})
    if not declared:
        raise ConfigError(f"{path}: no [process.<name>] tables")
    wanted = environ.get("OPS_ENABLED_SERVICES", "all").strip()
    names = list(declared) if wanted in ("", "all") else [n.strip() for n in wanted.split(",") if n.strip()]
    unknown = [n for n in names if n not in declared]
    if unknown:
        raise ConfigError(f"OPS_ENABLED_SERVICES names {', '.join(unknown)}; the config has {', '.join(declared)}")
    missing: set[str] = set()
    specs: list[Spec] = []
    for name, p in declared.items():  # config order is start order, whatever order the setting lists them in
        if name not in names:
            continue
        specs.append(
            Spec(
                name=name,
                command=[_expand(str(a), environ, missing) for a in p["command"]],
                env={str(k): _expand(str(v), environ, missing) for k, v in p.get("env", {}).items()},
                ready=_expand(str(p["ready"]), environ, missing) if "ready" in p else None,
                check=_expand(str(p["check"]), environ, missing) if "check" in p else None,
                ready_timeout=float(p.get("ready_timeout", 120)),
                cwd=p.get("cwd"),
            )
        )
    if missing:
        raise ConfigError(f"unset in the environment: {', '.join(sorted(missing))}")
    return HostConfig(
        processes=specs,
        grace_seconds=float(host.get("grace_seconds", 20)),
        max_restarts=int(host.get("max_restarts", 5)),
        restart_window_seconds=float(host.get("restart_window_seconds", 300)),
        backoff_max_seconds=float(host.get("backoff_max_seconds", 30)),
        withhold=[str(w) for w in host.get("withhold", [])],
    )


def _log(line: str, out: TextIO = sys.stdout) -> None:
    out.write(f"[host] {line}\n")
    out.flush()


def _signal_group(pid: int, sig: signal.Signals) -> None:
    # A group that is gone answers ESRCH on Linux and, while its leader is an unreaped zombie, EPERM on macOS.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, sig)


def _pipe(name: str, stream: Any) -> None:
    for raw in iter(stream.readline, b""):
        sys.stdout.write(f"[{name}] {raw.decode(errors='replace')}")
        sys.stdout.flush()
    stream.close()


class Host:
    def __init__(self, config: HostConfig, environ: dict[str, str]) -> None:
        self.config = config
        self.environ = environ
        self.running = [Running(s) for s in config.processes]
        self.stopping = threading.Event()

    def _start(self, r: Running) -> None:
        inherited = {
            k: v for k, v in self.environ.items() if not any(fnmatch.fnmatchcase(k, w) for w in self.config.withhold)
        }
        env = {**inherited, **r.spec.env}
        r.start_error = None
        try:
            # Its own session, so a stop reaches the process group (a uv or node child of the command), not the host.
            r.proc = subprocess.Popen(
                r.spec.command,
                env=env,
                cwd=r.spec.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as e:
            r.proc, r.start_error = None, f"could not start: {e}"
            _log(f"{r.spec.name}: {r.start_error}")
            return
        threading.Thread(target=_pipe, args=(r.spec.name, r.proc.stdout), daemon=True).start()
        _log(f"{r.spec.name}: started pid {r.proc.pid}")

    def _wait_ready(self, r: Running) -> None:
        if not r.spec.ready:
            return
        deadline = time.monotonic() + r.spec.ready_timeout
        while time.monotonic() < deadline and not self.stopping.is_set():
            if r.exited():
                return  # the supervise loop restarts it
            try:
                with urllib.request.urlopen(r.spec.ready, timeout=2) as resp:
                    if resp.status < 500:
                        _log(f"{r.spec.name}: ready")
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.5)
        _log(f"{r.spec.name}: not ready after {r.spec.ready_timeout:.0f}s; starting the rest")

    def stop(self) -> None:
        for r in reversed(self.running):
            if r.proc is not None and r.proc.poll() is None:
                _signal_group(r.proc.pid, signal.SIGTERM)
        deadline = time.monotonic() + self.config.grace_seconds
        for r in reversed(self.running):
            if r.proc is None:
                continue
            try:
                r.proc.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                _log(f"{r.spec.name}: still running after {self.config.grace_seconds:.0f}s; killing")
            # The group may hold children that outlived the leader; nothing of a stopped process stays behind.
            _signal_group(r.proc.pid, signal.SIGKILL)
            r.proc.wait()

    def run(self) -> int:
        try:
            return self._supervise()
        finally:
            # Whatever ends the loop, an error in the host included, no process outlives it.
            self.stop()

    def _supervise(self) -> int:
        for r in self.running:
            if self.stopping.is_set():
                break
            self._start(r)
            self._wait_ready(r)
        code = 0
        while not self.stopping.is_set():
            now = time.monotonic()
            for r in self.running:
                if not r.exited():
                    continue
                if r.restart_at == 0.0:
                    r.exits = [t for t in r.exits if now - t < self.config.restart_window_seconds] + [now]
                    if len(r.exits) > self.config.max_restarts:
                        _log(
                            f"{r.spec.name}: exited {len(r.exits)} times in "
                            f"{self.config.restart_window_seconds:.0f}s; stopping the host"
                        )
                        code = 1
                        self.stopping.set()
                        break
                    delay = min(self.config.backoff_max_seconds, 2.0 ** (len(r.exits) - 1))
                    _log(f"{r.spec.name}: {r.how()}; restarting in {delay:.0f}s")
                    r.restart_at = now + delay
                elif now >= r.restart_at:
                    r.restart_at = 0.0
                    self._start(r)
            self.stopping.wait(0.2)
        _log(f"stopping (exit {code})")
        return code


def _running_commands() -> list[str]:
    lines: list[str] = []
    for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
        with contextlib.suppress(OSError):
            lines.append(cmdline.read_bytes().replace(b"\0", b" ").decode(errors="replace").strip())
    return lines


def check(config: HostConfig) -> int:
    """One line per enabled process, up or down; exit 1 when any is down."""
    running = _running_commands()
    down = 0
    for spec in config.processes:
        url = spec.check or spec.ready
        if url:
            try:
                with urllib.request.urlopen(url, timeout=5) as resp:
                    state = f"{resp.status} {url}"
                    ok = resp.status < 400
            except urllib.error.HTTPError as e:
                state, ok = f"{e.code} {url}", False
            except (urllib.error.URLError, OSError) as e:
                state, ok = f"unreachable {url}: {e}", False
        else:
            ok = any(" ".join(spec.command) in line for line in running)
            state = "running" if ok else "not running"
        down += not ok
        print(f"{'ok  ' if ok else 'DOWN'} {spec.name}: {state}")
        if url and ok:
            down += _background(spec.name, url)
    return 1 if down else 0


def _background(name: str, url: str) -> int:
    """The process's background processes from its /health/background (c-516), one line each; late or stopped counts
    as down, as `make health` reads it locally. A service with no such route has none."""
    parts = urllib.parse.urlsplit(url)
    try:
        with urllib.request.urlopen(f"{parts.scheme}://{parts.netloc}/health/background", timeout=5) as resp:
            processes = json.loads(resp.read())["processes"]
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return 0
    down = 0
    for p in processes:
        bad = p["state"] in ("late", "stopped")
        down += bad
        print(f"{'DOWN' if bad else 'ok  '} {name} background {p['key']}: {p['state'].replace('_', ' ')}")
    return down


def main(argv: list[str]) -> int:
    checking = len(argv) == 3 and argv[1] == "--check"
    if checking:
        argv = [argv[0], argv[2]]
    if len(argv) != 2:
        print("usage: ops_host.py [--check] <config.toml>", file=sys.stderr)
        return 2
    environ = dict(os.environ)
    try:
        config = load(Path(argv[1]), environ)
    except (ConfigError, OSError, tomllib.TOMLDecodeError, KeyError) as e:
        print(f"[host] refusing to start: {e}", file=sys.stderr)
        return 2
    if checking:
        return check(config)
    host = Host(config, environ)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda _sig, _frame: host.stopping.set())
    _log("starting " + ", ".join(s.name for s in config.processes))
    return host.run()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
