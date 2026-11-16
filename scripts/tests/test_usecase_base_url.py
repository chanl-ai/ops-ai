"""OPS_USECASE_BASE_URL, by failure mode: a script run against a deployed host started its own services anyway, or ran
migrations and seeds against the host's database; and with it unset the harness changed nothing."""

from __future__ import annotations

import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNIPPET = """
import sys
sys.path.insert(0, {lib!r})
import usecase_harness as h
h._GUARDED = True  # the host and script rules are tested in test_usecase_deployed_guard.py
ran = h._prepare([sys.executable, "-c", "print('ran')"], check=True, capture_output=True)
print("prepared", ran is not None, flush=True)
with h._serve("agents", ["false"], 1, {{}}) as base:
    print("base", base)
"""


class Health(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        return


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    code = SNIPPET.format(lib=str(ROOT / "docs/usecases/lib"))
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=False)


def test_a_deployed_host_is_called_and_nothing_is_started_or_migrated() -> None:
    server = HTTPServer(("127.0.0.1", 0), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        done = _run({"OPS_USECASE_BASE_URL": url + "/", "PATH": ""})
        assert done.returncode == 0, done.stderr
        assert "prepared False" in done.stdout and f"base {url}\n" in done.stdout
    finally:
        server.shutdown()


def test_without_it_the_harness_still_runs_its_own_commands() -> None:
    done = _run({"PATH": "", "OPS_USECASE_AGENTS_PORT": "1"})
    assert "prepared True" in done.stdout and "base " not in done.stdout, done.stdout
