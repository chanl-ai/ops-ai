"""A use case page whose Details row names the platform services gets them (docs/usecases/lib/page_stack.py), as a ui
script gets them from the harness (packages/usecase-runner/src/harness.ts resolveStack): the page's people are signed
in through platform-service and each profile carries that person's own tokens. Before, such a page was refused before
any step ran. Real PostgreSQL and the real services, on free ports and a throwaway database dropped at the end."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PG_PORT = os.environ.get("OPS_PG_PORT", "5477")
DB = f"ops_usecase_t{os.getpid()}"


def _free() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return str(s.getsockname()[1])


def test_a_page_naming_platform_services_gets_them_with_its_people_signed_in(tmp_path: Path) -> None:
    config = tmp_path / "ops-config.json"
    ports = {
        f"OPS_USECASE_{name}_PORT": _free()
        for name in ("AGENTS", "TOOLS", "MODELS", "KB", "FILES", "PLATFORM", "PLATFORM_INTERNAL")
    }
    env = os.environ | ports | {"OPS_USECASE_DB": DB, "OPS_LOG_DIR": str(tmp_path / "logs")}
    argv = [
        *("uv", "run", "--quiet", "--directory", str(ROOT / "services/agents-service"), "python"),
        str(ROOT / "docs/usecases/lib/page_stack.py"),
        *("--config", str(config), "--profiles", "builder,viewer"),
        *("--services", "platform, agents and models services on the scripted model"),
    ]
    proc = subprocess.Popen(argv, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    seen = ""
    try:
        deadline = time.monotonic() + 300
        assert proc.stdout is not None
        while time.monotonic() < deadline:
            line = proc.stdout.readline().decode()
            if not line and proc.poll() is not None:
                break
            seen += line
            if line.strip() == "READY":
                break
        assert "READY" in seen, seen[-2000:]
        saved = json.loads(config.read_text())
        builder, viewer = saved["profiles"]["builder"], saved["profiles"]["viewer"]
        assert builder["accessToken"] and viewer["accessToken"] and builder["accessToken"] != viewer["accessToken"]
        assert builder["team"] == "team_ops"
        assert {"platform", "agents", "tools", "models"} <= set(builder["services"])
    finally:
        if proc.stdin:
            proc.stdin.close()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        drop = f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)"
        subprocess.run(
            ["psql", f"postgresql://ops:ops@localhost:{PG_PORT}/postgres", "-c", drop], capture_output=True, check=False
        )
