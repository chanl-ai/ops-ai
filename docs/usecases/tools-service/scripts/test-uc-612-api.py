"""uc-612 an install turns a feature on or off from its config, api layer:
docs/usecases/tools-service/an-install-turns-a-feature-on.md. A misspelt flag stops a service at start; with no flags
the MCP address answers 404 feature_off and the console's answer lists every flag off; with OPS_FLAGS=mcp_gateway the
adapter serves and the answer says on. No model call."""

from __future__ import annotations

import os
import subprocess
from contextlib import ExitStack

import httpx
from usecase_harness import (
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    ROOT,
    TOOLS_PORT,
    as_role,
    check,
    data,
    finish,
    pg_url,
    platform,
    tools,
)

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
MCP = f"http://127.0.0.1:{TOOLS_PORT}/mcp/test/team_ops"
LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
ACCEPT = {"Accept": "application/json, text/event-stream"}


def start_refused(service: str, module: str, port_setting: str) -> tuple[bool, str]:
    """Starts a service with a misspelt flag; it must exit on its own, naming the flag."""
    env = {
        # Only what uv needs, so no flag or service address from the caller's environment reaches the service.
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", str(ROOT)),
        "OPS_FLAGS": "mcp_gatway",
        "OPS_DATABASE_URL": pg_url(),
        port_setting: str(TOOLS_PORT),
    }
    try:
        p = subprocess.run(
            ["uv", "run", "python", "-m", module],
            cwd=ROOT / "services" / service,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"{service} kept running"
    return p.returncode != 0 and "unknown flag mcp_gatway in OPS_FLAGS" in p.stderr, p.stderr[-300:]


def flags_of(api: httpx.Client) -> dict[str, bool]:
    return {f["name"]: f["on"] for f in data(api.get("/v1/me", headers=as_role(api, "admin")))["flags"]}


def mcp_answer() -> tuple[int, str]:
    r = httpx.post(MCP, json=LIST, headers=ACCEPT, timeout=30)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return r.status_code, body.get("error", {}).get("code", "")


# 1. A misspelt flag in the install config stops each service at start.
ok, detail = start_refused("tools-service", "ops_tools", "OPS_GATEWAY_PORT")
check("1 tools-service refuses to start on a misspelt flag, naming it", ok, detail)
ok, detail = start_refused("platform-service", "ops_platform", "OPS_PLATFORM_PORT")
check("1 platform-service refuses to start on a misspelt flag, naming it", ok, detail)

# 2. No flags: every flag off, the MCP address says it is off.
with ExitStack() as stack:
    none = {"OPS_FLAGS": ""}
    api, _ = stack.enter_context(platform(env=none))
    stack.enter_context(tools({**AUTH, **none}))
    flags = flags_of(api)
    check("2 the console's answer lists mcp_gateway, off", flags.get("mcp_gateway") is False, flags)
    check("2 every flag is off with OPS_FLAGS unset", not any(flags.values()), flags)
    check("2 /mcp answers 404 feature_off", mcp_answer() == (404, "feature_off"), mcp_answer())

# 3. OPS_FLAGS=mcp_gateway: the answer says on and the MCP adapter serves (it asks an anonymous caller to sign in).
with ExitStack() as stack:
    on = {"OPS_FLAGS": "mcp_gateway"}
    api, _ = stack.enter_context(platform(env=on))
    stack.enter_context(tools({**AUTH, **on}))
    flags = flags_of(api)
    check("3 the console's answer says mcp_gateway is on", flags.get("mcp_gateway") is True, flags)
    check(
        "3 /mcp is served: an anonymous caller is asked to sign in", mcp_answer() == (401, "unauthorized"), mcp_answer()
    )

finish()
